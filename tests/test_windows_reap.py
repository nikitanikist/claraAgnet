import sys
import types

from clara.windows_reap import select_victims, reap


def tree():
    # worker (python) -> claude -> {node (browser bridge) -> chrome, python (windows bridge) -> T1TXP}
    return [{'pid': 10, 'ppid': 9, 'name': 'python.exe', 'created': 100},
            {'pid': 20, 'ppid': 10, 'name': 'claude.exe', 'created': 500},
            {'pid': 21, 'ppid': 20, 'name': 'node.exe', 'created': 501},
            {'pid': 22, 'ppid': 21, 'name': 'chrome.exe', 'created': 502},
            {'pid': 23, 'ppid': 20, 'name': 'python.exe', 'created': 501},
            {'pid': 24, 'ppid': 23, 'name': 'T1TXP.EXE', 'created': 560},
            {'pid': 30, 'ppid': 10, 'name': 'python.exe', 'created': 90},   # started before the task
            {'pid': 40, 'ppid': 1, 'name': 'claude.exe', 'created': 600}]   # not in the tree


def test_only_executors_started_with_the_task_are_selected_child_first():
    victims = select_victims(tree(), 20, 500, {10})
    assert victims in ([21, 23, 20], [23, 21, 20])
    assert 22 not in victims and 24 not in victims, 'applications stay open for review'
    assert 30 not in victims and 40 not in victims


def test_worker_root_never_selects_the_worker_or_older_children():
    victims = select_victims(tree(), 10, 500, {10})
    assert 10 not in victims and 30 not in victims
    assert set(victims) == {20, 21, 23}
    assert victims.index(21) < victims.index(20) and victims.index(23) < victims.index(20)


def test_reap_terminates_then_kills_survivors_and_reports_them(monkeypatch):
    calls = []

    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    class Proc:
        def __init__(self, pid):
            row = next((r for r in tree() if r['pid'] == pid), None)
            if row is None:
                raise NoSuchProcess()
            self.pid, self._row = pid, row
        def children(self, recursive=False):
            rows = tree()
            out, stack = [], [self.pid]
            while stack:
                parent = stack.pop()
                for r in rows:
                    if r['ppid'] == parent:
                        out.append(Proc(r['pid'])); stack.append(r['pid'])
            return out
        def ppid(self): return self._row['ppid']
        def name(self): return self._row['name']
        def create_time(self): return self._row['created']
        def terminate(self):
            if self.pid == 23:
                raise AccessDenied()
            calls.append(('terminate', self.pid))
        def kill(self): calls.append(('kill', self.pid))

    def wait_procs(handles, timeout):
        gone = [h for h in handles if h.pid != 21]
        return gone, [h for h in handles if h.pid == 21]

    fake = types.SimpleNamespace(Process=Proc, NoSuchProcess=NoSuchProcess, AccessDenied=AccessDenied, wait_procs=wait_procs)
    monkeypatch.setitem(sys.modules, 'psutil', fake)
    result = reap(20, 500, {10})
    assert ('terminate', 21) in calls and ('terminate', 20) in calls and ('kill', 21) in calls
    assert all(pid not in (22, 24, 10, 30) for _, pid in calls)
    assert {t['pid'] for t in result['terminated']} == {20, 21} and result['failed'] == [23]
    assert reap(999, 500, {10})['missing'] is True
