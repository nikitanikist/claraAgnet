"""End the model/script executors a finished or stopped task left running.

Run by the separate desktop Python (the one with psutil). The Claude CLI and
its MCP bridges are children of the worker; a bare asyncio cancellation can
leave them alive after a stop, and the activity observer then reports them as
unfinished execution for ever. This ends only those executor processes, child
first. Application windows (TaxPrep, Chrome, Word, ...) are never touched: they
stay open as unresolved observations for the operator's review.
"""
import json
import os
import sys

EXECUTORS = {'claude.exe', 'node.exe', 'python.exe', 'pythonw.exe', 'powershell.exe', 'pwsh.exe',
             'cmd.exe', 'wscript.exe', 'cscript.exe', 'claude', 'node', 'python', 'python3'}
GRACE_S = 5


def select_victims(rows, root_pid, since, protected):
    """Executor processes in root_pid's tree created at or after `since`, deepest first.

    rows: [{'pid', 'ppid', 'name', 'created'}]. Processes in `protected` (the
    worker, this script) are never selected; nothing outside the tree is.
    """
    by_parent = {}
    for row in rows:
        by_parent.setdefault(row['ppid'], []).append(row['pid'])
    info = {row['pid']: row for row in rows}
    ordered, stack, seen = [], [root_pid], set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)
        stack.extend(by_parent.get(pid, []))
    victims = []
    for pid in reversed(ordered):  # every process after all of its descendants
        row = info.get(pid)
        if (not row or pid in protected or str(row.get('name', '')).casefold() not in EXECUTORS
                or row['created'] < since - 5):
            continue
        victims.append(pid)
    return victims


def reap(root_pid, since, protected):
    import psutil
    try:
        root = psutil.Process(root_pid)
        tree = [root, *root.children(recursive=True)]
    except psutil.NoSuchProcess:
        return {'root': root_pid, 'missing': True, 'terminated': [], 'failed': []}
    rows = []
    for process in tree:
        try:
            rows.append({'pid': process.pid, 'ppid': process.ppid(), 'name': process.name(),
                         'created': process.create_time()})
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    victims = select_victims(rows, root_pid, since, set(protected) | {os.getpid()})
    handles, failed = [], []
    for pid in victims:
        try:
            handle = psutil.Process(pid)
            handle.terminate()  # TerminateProcess on Windows; no application window is in this list
            handles.append(handle)
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, OSError):
            failed.append(pid)
    gone, alive = psutil.wait_procs(handles, timeout=GRACE_S)
    for handle in alive:
        try:
            handle.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            failed.append(handle.pid)
    names = {row['pid']: row['name'] for row in rows}
    return {'root': root_pid, 'missing': False,
            'terminated': [{'pid': h.pid, 'name': names.get(h.pid, '')} for h in [*gone, *alive] if h.pid not in failed],
            'failed': failed}


def main(argv):
    root_pid, since = int(argv[1]), float(argv[2])
    protected = {int(value) for value in argv[3:]}
    print(json.dumps(reap(root_pid, since, protected)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
