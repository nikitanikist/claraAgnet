"""Fresh Windows observations around the pinned Windows-MCP runtime.

Runs in the separate desktop Python. Imports are lazy so control logic is testable
on Mac; UI Automation objects never cross COM thread boundaries.
"""
import json
import time


def choose_window(windows, name):
    exact = [w for w in windows if w['title'].casefold() == name.casefold()]
    matches = exact or [w for w in windows if name.casefold() in w['title'].casefold()]
    if len(matches) != 1:
        raise ValueError('Window missing or ambiguous. Use ListWindows and a specific handle/PID.')
    return matches[0]


def fresh_windows():
    import win32gui, win32process
    result = []
    def visit(handle, _):
        if win32gui.IsWindowVisible(handle) and win32gui.GetWindowText(handle):
            pid = win32process.GetWindowThreadProcessId(handle)[1]
            result.append({'handle':handle, 'pid':pid, 'title':win32gui.GetWindowText(handle),
                           'class':win32gui.GetClassName(handle), 'rect':list(win32gui.GetWindowRect(handle)),
                           'foreground':handle == win32gui.GetForegroundWindow()})
    win32gui.EnumWindows(visit, None)
    return result


def require_window(handle, pid):
    found = next((w for w in fresh_windows() if w['handle'] == handle and w['pid'] == pid), None)
    if not found:
        raise ValueError('Window disappeared or its identity changed. Inspect fresh windows.')
    return found


def focus(handle, pid, desktop):
    import win32gui, win32con
    require_window(handle, pid)
    if win32gui.IsIconic(handle):
        win32gui.ShowWindow(handle, win32con.SW_RESTORE)
    desktop.bring_window_to_top(handle)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        window = require_window(handle, pid)
        if window['foreground']:
            return window
        time.sleep(.05)
    raise ValueError('Windows did not give this application focus. No keys or clicks were sent.')


def walk_controls(root, limit=180):
    queue = [(root, [], 0)]; rows = []; deadline = time.monotonic()+3
    while queue and len(rows)<limit and time.monotonic()<deadline:
        control, path, depth = queue.pop(0)
        try:
            row = {'path':path, 'name':control.Name[:300], 'automation_id':control.AutomationId,
                   'type':control.ControlTypeName, 'enabled':control.IsEnabled}
            rows.append((row, control))
            if depth < 6:
                queue.extend((child, path+[i], depth+1) for i,child in enumerate(control.GetChildren()[:80]))
        except Exception:
            continue
    return rows, bool(queue)


def inspect(handle, pid):
    import windows_mcp.uia as uia
    window = require_window(handle, pid)
    with uia.UIAutomationInitializerInThread():
        rows, truncated = walk_controls(uia.ControlFromHandle(handle))
        return {'window':window, 'controls':[r for r,c in rows], 'truncated':truncated,
                'observed_at':time.time(), 'note':'Paths are observations, not permanent selectors.'}


def application_info(handle,pid):
    import ctypes
    from ctypes import wintypes
    import win32api
    window=require_window(handle,pid)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    process=kernel.OpenProcess(0x1000,False,pid)
    if not process: raise ValueError('Application metadata is unavailable with this Windows account.')
    try:
        buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(process,0,buffer,ctypes.byref(size)): raise ValueError('Cannot read executable path.')
        version=win32api.GetFileVersionInfo(buffer.value,'\\')
        hi,lo=version['FileVersionMS'],version['FileVersionLS']
        return {'window':window,'executable':buffer.value,'build':f'{hi>>16}.{hi&65535}.{lo>>16}.{lo&65535}'}
    finally: kernel.CloseHandle(process)


def verify_window(handle,pid,title_parts):
    if not title_parts or any(not isinstance(p,str) or not p.strip() for p in title_parts):
        raise ValueError('Provide expected client/file/year title text from the task.')
    window=require_window(handle,pid)
    checks=[{'title_contains':p,'passed':p.casefold() in window['title'].casefold()} for p in title_parts[:8]]
    return {'clara_observation':True,'kind':'desktop_assertion','window':window,'checks':checks,
            'verified':all(c['passed'] for c in checks),'coverage':'Live window title/PID only; client values inside forms still require inspection.'}


def select_control(rows, selector):
    allowed = {'name','automation_id','type'}
    if not selector or set(selector)-allowed or not any(selector.values()):
        raise ValueError('Use a nonempty name/automation_id/type selector from live controls.')
    matches = [(r,c) for r,c in rows if all(r.get(k)==v for k,v in selector.items())]
    if len(matches)!=1:
        raise ValueError('Control missing or ambiguous; inspect live controls before retrying.')
    return matches[0][1]


def act(handle, pid, steps, expected, desktop):
    import windows_mcp.uia as uia
    if not 1<=len(steps)<=6 or not expected:
        raise ValueError('Use 1–6 actions and at least one expected control selector.')
    completed = []
    with uia.UIAutomationInitializerInThread():
        for step in steps:
            focus(handle, pid, desktop)
            action = step.get('action')
            if action == 'shortcut':
                desktop.shortcut(step['keys'])
            else:
                rows, _ = walk_controls(uia.ControlFromHandle(handle))
                control = select_control(rows, step.get('selector',{}))
                if not control.IsEnabled:
                    raise ValueError('The selected control is disabled.')
                patterns = {'invoke':('InvokePattern','Invoke'), 'set_value':('ValuePattern','SetValue'),
                            'select':('SelectionItemPattern','Select'), 'toggle':('TogglePattern','Toggle')}
                if action not in patterns:
                    raise ValueError('Use invoke, set_value, select, toggle or shortcut.')
                pattern_name, method = patterns[action]
                pattern = control.GetPattern(getattr(uia.PatternId, pattern_name))
                if not pattern:
                    raise ValueError('Control does not support this pattern. Inspect before choosing a visual fallback.')
                getattr(pattern, method)(str(step.get('text',''))) if action=='set_value' else getattr(pattern, method)()
            completed.append(action)
        deadline = time.monotonic()+3
        checks = []
        while True:
            window = require_window(handle,pid)
            rows,truncated = walk_controls(uia.ControlFromHandle(handle))
            checks=[]
            for selector in expected[:8]:
                try:
                    select_control(rows,selector);ok=True
                except ValueError:
                    ok=False
                checks.append({'selector':selector,'passed':ok})
            if all(c['passed'] for c in checks) or time.monotonic()>=deadline:
                break
            time.sleep(.1)
    return {'clara_observation':True, 'kind':'desktop_assertion', 'verified':all(c['passed'] for c in checks),
            'window':window,'checks':checks,'completed_actions':completed, 'truncated':truncated,
            'coverage':'Expected accessible controls were observed; this does not verify accounting correctness.'}


def main():
    import windows_mcp.__main__ as native
    from windows_mcp.desktop.service import Desktop
    # Replace the cached-title switch path, keeping the remaining pinned tools.
    def switch(self, name):
        w=choose_window(fresh_windows(),name)
        focus(w['handle'],w['pid'],self)
        return f"Foreground verified: {w['title']} (PID {w['pid']}).",0
    Desktop.switch_app=switch
    mcp=native._build_mcp()
    @mcp.tool(name='ListWindows')
    def list_windows() -> dict:
        """List live visible windows, handles and PIDs without a full accessibility scan."""
        return {'windows':fresh_windows()}
    @mcp.tool(name='FocusWindow')
    def focus_window(handle:int,pid:int) -> dict:
        """Focus this exact live window and verify foreground identity before further actions."""
        return focus(handle,pid,native._get_desktop())
    @mcp.tool(name='InspectControls')
    def inspect_controls(handle:int,pid:int) -> dict:
        """Bounded accessibility inspection of one application window."""
        return inspect(handle,pid)
    @mcp.tool(name='ApplicationInfo')
    def app_info(handle:int,pid:int) -> dict:
        """Read executable path and actual file build for this exact Windows application."""
        return application_info(handle,pid)
    @mcp.tool(name='VerifyWindow')
    def verify(handle:int,pid:int,title_parts:list[str]) -> dict:
        """Check live window identity/title against expected client, file and year text without taking actions."""
        return verify_window(handle,pid,title_parts)
    @mcp.tool(name='ActAndVerify')
    def act_and_verify(handle:int,pid:int,steps:list[dict],expected:list[dict]) -> dict:
        """Execute at most six focused actions then verify expected accessible controls. On errors, inspect before retrying; earlier actions may have happened."""
        return act(handle,pid,steps,expected,native._get_desktop())
    native._apply_tool_filter(mcp, None, ['PowerShell','Registry','FileSystem','Process'])
    import sys
    if '--probe' in sys.argv:
        print('Clara Windows bridge registered. Live focus/control checks still require an interactive desktop.')
        return
    mcp.run(transport='stdio',show_banner=False)


if __name__=='__main__':
    main()
