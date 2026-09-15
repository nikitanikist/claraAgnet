"""Read-only Windows activity probe, run by the separate desktop Python.

No document titles, command lines, credentials or client paths are returned.
This observes the current session; it never closes a window or kills a process.
"""
import ctypes
import hashlib
import json
import os
import sys
import time


def snapshot(controller_pid):
    import psutil
    import win32api
    import win32gui
    import win32print
    import win32process
    import win32security
    import win32ts
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.ProcessIdToSessionId.restype = wintypes.BOOL

    def session_of(pid):
        value = wintypes.DWORD()
        if not kernel.ProcessIdToSessionId(pid, ctypes.byref(value)):
            raise OSError('Session identity unavailable')
        return value.value

    session = session_of(os.getpid())
    if session_of(controller_pid) != session:
        raise ValueError('The observer must run in the worker interactive session.')
    controller = psutil.Process(controller_pid)
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetShellWindow.argtypes = []
    user32.GetShellWindow.restype = wintypes.HWND
    shell_window = user32.GetShellWindow()
    shell_pid = win32process.GetWindowThreadProcessId(shell_window)[1] if shell_window else 0
    desktop = user32.OpenInputDesktop(0, False, 0x0100)
    accessible = bool(desktop)
    if desktop:
        user32.CloseDesktop(desktop)
    active = win32ts.WTSQuerySessionInformation(None, session, win32ts.WTSConnectState) == win32ts.WTSActive
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    username, domain, _ = win32security.LookupAccountSid(None, sid)
    print_owners = {username.casefold(), (domain + '\\' + username).casefold()}
    result = {'version': 1, 'observed_at': time.time(), 'boot': psutil.boot_time(),
              'session': session, 'interactive': accessible and active,
              'owner': hashlib.sha256(str(sid).encode()).hexdigest(),
              'controller': [controller.pid, controller.create_time()],
              'ancestors': [p.pid for p in controller.parents()] + [controller.pid],
              'processes': [], 'windows': [], 'print_jobs': [], 'errors': [], 'shell_pid': shell_pid,
              'unresolved_processes': [], 'window_details': [], 'ui_process_ids': []}
    for process_session, pid, name, process_sid in win32ts.WTSEnumerateProcesses():
        if process_session != session or pid in {0, os.getpid()}:
            continue
        if process_sid is None:
            # WTS can omit a SID even when the process token is readable. Ask
            # for limited query access only; never elevate or infer ownership
            # from an executable name. Even with no SID, the process is tracked
            # below by PID + creation time. No current-session process is omitted.
            process_handle = process_token = None
            try:
                process_handle = win32api.OpenProcess(0x1000, False, pid)
                process_token = win32security.OpenProcessToken(process_handle, win32security.TOKEN_QUERY)
                process_sid = win32security.GetTokenInformation(process_token, win32security.TokenUser)[0]
            except Exception:
                if psutil.pid_exists(pid):
                    result['unresolved_processes'].append({'pid': pid, 'name': name})
            finally:
                if process_token is not None:
                    process_token.Close()
                if process_handle is not None:
                    process_handle.Close()
        # Include SYSTEM/protected-account processes in this same session too.
        # Ownership is not needed for before/after activity tracking, provided
        # the process creation identity is readable. Missing identity remains
        # an error; a new/reused PID is never waved through as a system process.
        try:
            process = psutil.Process(pid)
            result['processes'].append({'pid': pid, 'created': process.create_time(), 'name': process.name()})
        except psutil.NoSuchProcess:
            continue
        except (OSError, psutil.AccessDenied):
            if psutil.pid_exists(pid):
                result['errors'].append('process-unreadable:' + str(pid))

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            row = {'handle': hwnd, 'pid': pid, 'class': win32gui.GetClassName(hwnd)}
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width, height = right - left, bottom - top
            result['window_details'].append({**row, 'width': width, 'height': height})
            # A WS_VISIBLE flag alone includes zero-size shell/console helper
            # windows. These have no visible app surface. Processes and print
            # queues are observed separately, including background applications.
            if width > 0 and height > 0:
                result['windows'].append(row)
                result['ui_process_ids'].append(pid)
                # Hosted Windows apps can own a child surface while the top
                # window belongs to ApplicationFrameHost. Record IDs only.
                def child_surface(child, _):
                    if win32gui.IsWindowVisible(child):
                        x1, y1, x2, y2 = win32gui.GetWindowRect(child)
                        if x2 > x1 and y2 > y1:
                            result['ui_process_ids'].append(win32process.GetWindowThreadProcessId(child)[1])
                    return True
                win32gui.EnumChildWindows(hwnd, child_surface, None)
    win32gui.EnumWindows(visit, None)
    result['ui_process_ids'] = sorted(set(result['ui_process_ids']))

    # Enumerate every configured queue for this account's work. An unreadable
    # queue is unknown, not empty. Retained/paused jobs remain blockers.
    printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS, None, 4)
    for printer in printers:
        name = printer['pPrinterName']
        queue_id = hashlib.sha256(name.encode()).hexdigest()[:16]
        handle = None
        try:
            handle = win32print.OpenPrinter(name)
            offset = 0
            while True:
                page = win32print.EnumJobs(handle, offset, 100, 1)
                for job in page:
                    if not job.get('pUserName'):
                        result['errors'].append('print-owner-unreadable:' + queue_id)
                    elif job['pUserName'].casefold() in print_owners:
                        result['print_jobs'].append({'queue': queue_id, 'id': job['JobId'], 'status': job['Status']})
                if len(page) < 100:
                    break
                offset += len(page)
                if offset >= 10000:
                    raise ValueError('Print queue too large to observe completely')
        except Exception:
            result['errors'].append('print-queue-unreadable:' + queue_id)
        finally:
            if handle is not None:
                win32print.ClosePrinter(handle)
    return result


if __name__ == '__main__':
    try:
        if os.name != 'nt':
            raise ValueError('Windows required')
        print(json.dumps(snapshot(int(sys.argv[1])), allow_nan=False))
    except Exception:
        # Native errors can contain printer names or paths. Keep these local
        # observation failures generic; they never turn into a quiet receipt.
        print(json.dumps({'version': 1, 'errors': ['windows-observation-unavailable']}))
        sys.exit(1)
