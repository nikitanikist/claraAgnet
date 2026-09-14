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
              'processes': [], 'windows': [], 'print_jobs': [], 'errors': []}
    for process_session, pid, name, process_sid in win32ts.WTSEnumerateProcesses():
        if process_session != session or pid in {0, os.getpid()}:
            continue
        if process_sid is None:
            result['errors'].append('process-owner-unreadable:' + str(pid))
            continue
        if process_sid != sid:
            continue
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
            result['windows'].append({'handle': hwnd, 'pid': pid, 'class': win32gui.GetClassName(hwnd)})
    win32gui.EnumWindows(visit, None)

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
