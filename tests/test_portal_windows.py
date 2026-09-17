import asyncio
import copy
from dataclasses import asdict
import json
import time

import pytest

from clara.portal_bindings import PortalBindings
from clara.portal_journal import PortalJournal
from clara.agent import AgentManager
from clara.portal_windows import WindowsHandoff, validate_snapshot, baseline_issues, baseline_notes, task_started_processes
from test_portal_delivery import BASE, WORKER, setup


def sample():
    return {'version': 1, 'observed_at': time.time(), 'boot': 100, 'session': 3,
            'interactive': True, 'owner': 'a' * 64, 'controller': [10, 110], 'ancestors': [9, 10],
            'processes': [{'pid': 10, 'created': 110, 'name': 'python.exe'},
                          {'pid': 9, 'created': 105, 'name': 'powershell.exe'}],
            'windows': [{'handle': 1, 'pid': 9, 'class': 'ConsoleWindowClass'}],
            'print_jobs': [], 'errors': []}


def task(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare this T1')['local_job_id']
    store.status(jid, 'needs_review')  # Human email review is expected, not task failure.
    journal = PortalJournal(store, BASE)
    row = journal.stage(lease.identity, 'clara-result', 'result-' + jid,
                        {**asdict(lease.identity), 'outcome': 'completed_prepared'})
    journal.acknowledge(row['id'], {'accepted': True})
    return store, jid


def test_quiet_success_requires_fresh_observations_and_an_unchanged_saved_baseline(tmp_path):
    store, jid = task(tmp_path)
    current, clock = sample(), [0]
    observer = WindowsHandoff(store, exclusive=True, qualified=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        await observer.begin(jid)
        original = store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot']
        # A live detached process keeps the worker busy even though the command returned.
        current['processes'].append({'pid': 55, 'created': 200, 'name': 'python.exe'})
        await observer.begin(jid)
        assert store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot'] == original
        report = await observer.observe(jid)
        assert report['in_flight'] == ['windows-process:55:200']
        current['processes'].pop()
        assert (await observer.observe(jid))['in_flight'] == ['windows-settling']
        clock[0] = 4
        assert (await observer.observe(jid))['complete']
        # A new print invalidates the earlier quiet period; it must settle afresh.
        current['print_jobs'] = [{'queue': 'printer', 'id': 42, 'status': 0}]
        assert (await observer.observe(jid))['in_flight'] == ['windows-print:printer:42']
        current['print_jobs'] = []
        assert not (await observer.observe(jid))['complete']
        clock[0] = 8
        assert (await observer.observe(jid))['complete']
    asyncio.run(scenario())


@pytest.mark.parametrize('change,expected', [
    (lambda s: s['processes'].append({'pid': 9, 'created': 999, 'name': 'other.exe'}), 'windows-process:9:999'),
    (lambda s: s['windows'].append({'handle': 88, 'pid': 10, 'class': 'Dialog'}), 'windows-window:88:10'),
    (lambda s: s.update(session=4), 'windows-session-or-controller-changed'),
    (lambda s: s.update(controller=[10, 999]), 'windows-session-or-controller-changed'),
    (lambda s: s.update(owner='b' * 64), 'windows-session-or-controller-changed'),
    (lambda s: s.update(boot=999), 'windows-session-or-controller-changed'),
    (lambda s: s.update(errors=['print-queue-unreadable']), 'windows-observation-unavailable'),
    (lambda s: s.update(interactive=False), 'windows-observation-unavailable'),
    (lambda s: s.update(observed_at=0), 'windows-observation-unavailable'),
])
def test_activity_and_uncertain_windows_observations_never_release(tmp_path, change, expected):
    store, jid = task(tmp_path)
    current = sample()
    observer = WindowsHandoff(store, exclusive=True, qualified=True, probe=lambda: copy.deepcopy(current))
    async def scenario():
        await observer.begin(jid)
        change(current)
        report = await observer.observe(jid)
        assert not report['complete']
        assert expected in report['in_flight'] + report['unknown']
    asyncio.run(scenario())


@pytest.mark.parametrize('blocked', ['unqualified', 'shared', 'missing-baseline', 'interrupted', 'no-receipt', 'printing-baseline'])
def test_operator_or_task_preconditions_cannot_be_replaced_by_a_quiet_desktop(tmp_path, blocked):
    store, jid = task(tmp_path)
    current = sample()
    if blocked == 'printing-baseline':
        current['print_jobs'].append({'queue': 'printer', 'id': 1, 'status': 0})
    observer = WindowsHandoff(store, exclusive=blocked != 'shared', qualified=blocked != 'unqualified',
                              probe=lambda: copy.deepcopy(current))
    async def scenario():
        if blocked != 'missing-baseline':
            await observer.begin(jid)
        if blocked == 'interrupted':
            store.status(jid, 'interrupted')
        if blocked == 'no-receipt':
            store.execute("DELETE FROM portal_v1_outbox WHERE operation='clara-result'")
        if blocked == 'printing-baseline':
            current['print_jobs'].clear()
        report = await observer.observe(jid)
        assert not report['complete'] and report['unknown']
    asyncio.run(scenario())


def test_cleanup_identifies_only_new_application_windows_without_closing_them(tmp_path):
    store, jid = task(tmp_path)
    current = sample()
    observer = WindowsHandoff(store, probe=lambda: copy.deepcopy(current))
    async def scenario():
        await observer.begin(jid)
        current['windows'].append({'handle': 88, 'pid': 55, 'class': 'TaxPrep'})
        current['processes'].append({'pid': 55, 'created': 200, 'name': 'T1Txp.exe'})
        assert await observer.cleanup_hint(jid) == [{'handle': 88, 'pid': 55, 'class': 'TaxPrep', 'application': 'T1Txp.exe'}]
        assert len(current['windows']) == 2
    asyncio.run(scenario())


def test_failed_probe_persists_unknown_baseline_instead_of_retrying_it_as_clean(tmp_path):
    store, jid = task(tmp_path)
    observer = WindowsHandoff(store, probe=lambda: {'version': 1, 'errors': ['failure']})
    async def scenario():
        await observer.begin(jid)
        observer.probe = sample
        await observer.begin(jid)
        assert 'windows-baseline-unavailable' in (await observer.observe(jid))['unknown']
    asyncio.run(scenario())


@pytest.mark.parametrize('status', ['failed', 'incomplete', 'needs_review', 'completed'])
def test_failed_restart_reviews_apps_without_counting_current_worker_as_old_execution(tmp_path, status):
    # 'incomplete' (a stage's evidence no longer matched after the model finished)
    # is reviewed like a failed attempt: leftover apps are reviewable unknowns,
    # not in-flight work that would block the portal's Review and continue.
    store, jid = task(tmp_path)
    store.status(jid, status)
    current = sample()
    observer = WindowsHandoff(store, exclusive=True, qualified=False,
                              probe=lambda: copy.deepcopy(current))
    async def scenario():
        await observer.begin(jid)
        baseline = store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot']
        current.update(controller=[20, 220], ancestors=[19, 20])
        current['processes'] = [
            {'pid': 20, 'created': 220, 'name': 'python.exe'},
            {'pid': 19, 'created': 219, 'name': 'powershell.exe'},
            {'pid': 30, 'created': 230, 'name': 'msedge.exe'},
            {'pid': 31, 'created': 231, 'name': 'conhost.exe'},
        ]
        current['windows'] = [
            {'handle': 20, 'pid': 19, 'class': 'ConsoleWindowClass'},
            {'handle': 30, 'pid': 30, 'class': 'Chrome_WidgetWin_1'},
        ]
        report = await observer.observe(jid)
        assert report['in_flight'] == []
        assert not report['complete']
        # The console host (pid 31) is one of the helpers Windows starts for itself: never a leftover.
        expected = {'windows-process:30:230',
                    'windows-window:30:30', 'windows-session-or-controller-changed', 'windows-handoff-not-qualified'}
        if status not in {'needs_review', 'completed'}:
            expected.add('windows-interrupted-task-needs-review')  # a finished model turn is reviewed by the portal instead
        assert expected <= set(report['unknown'])
        assert not any(ref.startswith(('windows-process:20:', 'windows-process:19:', 'windows-window:20:'))
                       for ref in report['unknown'])
        assert store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot'] == baseline
        # A detached executor or print job cannot be dismissed as an idle app.
        current['processes'].append({'pid': 40, 'created': 240, 'name': 'node.exe'})
        current['print_jobs'] = [{'queue': 'printer', 'id': 5, 'status': 0}]
        report = await observer.observe(jid)
        assert set(report['in_flight']) == {'windows-process:40:240', 'windows-print:printer:5'}
    asyncio.run(scenario())


@pytest.mark.parametrize('update', [{'processes': None}, {'owner': None}, {'version': True}, {'observed_at': float('nan')}])
def test_snapshot_requires_complete_typed_observation(update):
    with pytest.raises(ValueError):
        validate_snapshot({**sample(), **update})


def test_unavailable_qualified_baseline_stops_before_query_or_application_actions(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare this T1')['local_job_id']
    manager = AgentManager(config, store)
    manager.execution_guards[jid] = lease
    manager.windows_handoff = WindowsHandoff(store, exclusive=True, qualified=True,
                                             probe=lambda: {**sample(), 'interactive': False})
    async def must_not_execute(*args):
        pytest.fail('A model task must not start with an unavailable qualified Windows baseline')
    manager._execute = must_not_execute
    async def scenario():
        with pytest.raises(ValueError, match='No model work started'):
            await manager.execute(store.job(jid))
        assert json.loads(store.job(jid)['usage'])['total_tokens'] == 0
        assert store.one('SELECT snapshot FROM portal_windows_baselines WHERE job_id=?', (jid,))
    asyncio.run(scenario())


def test_boot_estimate_jitter_does_not_change_exact_controller_identity(tmp_path):
    store, jid = task(tmp_path)
    current, clock = sample(), [0]
    observer = WindowsHandoff(store, exclusive=True, qualified=True,
                              probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        await observer.begin(jid)
        current['boot'] += 0.012
        assert (await observer.observe(jid))['in_flight'] == ['windows-settling']
        current['boot'] -= 0.026
        clock[0] = 4
        assert (await observer.observe(jid))['complete']
        current['controller'][1] += 0.001
        assert 'windows-session-or-controller-changed' in (await observer.observe(jid))['unknown']
    asyncio.run(scenario())


def test_shell_helpers_require_actual_shell_pid_and_explorer_folders_are_notes():
    current = sample()
    current['shell_pid'] = 20
    current['windows'] += [{'handle': 88, 'pid': 20, 'class': 'ThumbnailDeviceHelperWnd'},
                           {'handle': 89, 'pid': 20, 'class': 'EdgeUiInputTopWndClass'}]
    assert baseline_issues(current) == [] and baseline_notes(current) == []
    current['windows'].append({'handle': 90, 'pid': 20, 'class': 'CabinetWClass'})
    assert 'pre-existing-application-windows' in baseline_notes(current)
    current['windows'].pop()
    current['windows'][1]['pid'] = 30
    assert 'pre-existing-application-windows' in baseline_notes(current)
    assert baseline_issues(current) == [], 'programs already open are notes, never blockers'


def general_task(tmp_path):
    _, store, claim, lease = setup(tmp_path)
    claim.update(kind='general', closeout=None, required_outputs=[])
    claim['scope']['closeout_form_id'] = None
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Open the requested application')['local_job_id']
    store.status(jid, 'completed')
    journal = PortalJournal(store, BASE)
    row = journal.stage(lease.identity, 'clara-result', 'result-' + jid,
                        {**asdict(lease.identity), 'outcome': 'completed_prepared'})
    journal.acknowledge(row['id'], {'result_recorded': True, 'job_state': 'completed_prepared',
                                  'handoff': {'status': 'not_applicable'}})
    return store, jid


def test_completed_general_request_can_leave_its_app_visible_and_preserve_preexisting_chat(tmp_path):
    store, jid = general_task(tmp_path)
    current, clock = sample(), [0]
    current['processes'].append({'pid': 40, 'created': 150, 'name': 'messenger.exe'})
    current['windows'].append({'handle': 40, 'pid': 40, 'class': 'Messenger'})
    observer = WindowsHandoff(store, exclusive=True, qualified=False,
                              probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        assert await observer.begin(jid) == []
        baseline = store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot']
        current['processes'].append({'pid': 55, 'created': 200, 'name': 'CalculatorApp.exe'})
        current['windows'].append({'handle': 55, 'pid': 55, 'class': 'Calculator'})
        assert (await observer.observe(jid))['in_flight'] == ['windows-settling']
        clock[0] = 4
        assert (await observer.observe(jid))['complete']
        assert store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot'] == baseline
        assert len(current['windows']) == 3  # No automatic close of requested results.
    asyncio.run(scenario())


@pytest.mark.parametrize('blocker', ['background-command', 'visible-controller', 'printing', 'interrupted',
                                   'missing-receipt', 'wrong-handoff', 'shared', 'changed-controller', 'locked'])
def test_general_completion_still_requires_finished_work_receipt_and_current_desktop(tmp_path, blocker):
    store, jid = general_task(tmp_path)
    current = sample()
    observer = WindowsHandoff(store, exclusive=blocker != 'shared', probe=lambda: copy.deepcopy(current))
    async def scenario():
        await observer.begin(jid)
        if blocker in {'background-command', 'visible-controller'}:
            current['processes'].append({'pid': 55, 'created': 200, 'name': 'python.exe'})
            if blocker == 'visible-controller':
                current['windows'].append({'handle': 55, 'pid': 55, 'class': 'ConsoleWindowClass'})
        elif blocker == 'printing':
            current['print_jobs'].append({'queue': 'printer', 'id': 4, 'status': 0})
        elif blocker == 'interrupted':
            store.status(jid, 'interrupted')
        elif blocker == 'missing-receipt':
            store.execute("UPDATE portal_v1_outbox SET acknowledged=NULL")
        elif blocker == 'wrong-handoff':
            store.execute('UPDATE portal_v1_outbox SET receipt=?', (json.dumps({
                'result_recorded': True, 'job_state': 'completed_prepared', 'handoff': {'status': 'ready_to_email'}}),))
        elif blocker == 'changed-controller':
            current['controller'] = [999, 999]
        elif blocker == 'locked':
            current['interactive'] = False
        report = await observer.observe(jid)
        assert not report['complete']
        assert 'windows-settling' not in report['in_flight']
        assert report['unknown'] or report['in_flight']
    asyncio.run(scenario())


def test_stopped_task_reaps_its_own_executors_but_never_applications(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare this T1')['local_job_id']
    manager = AgentManager(config, store)
    reaped = []
    async def reaper(root_pid, since, protected):
        reaped.append((root_pid, since, list(protected)))
        return {'root': root_pid, 'missing': False, 'terminated': [{'pid': 21, 'name': 'node.exe'}], 'failed': []}
    manager.windows_handoff = WindowsHandoff(store, probe=lambda: sample(), reaper=reaper)
    connected = asyncio.Event()
    async def fake_execute(job, tracker, started, limit):
        manager.cli_pids[job['id']] = 4242   # what _cli_pid reports once the SDK session is up
        connected.set()
        await asyncio.sleep(3600)
    manager._execute = fake_execute
    async def scenario():
        worker = asyncio.create_task(manager.worker())
        manager.queue.put_nowait(jid)
        await asyncio.wait_for(connected.wait(), 5)
        before = time.time()
        await manager.cancel(jid)
        for _ in range(50):
            if reaped:
                break
            await asyncio.sleep(0.05)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        assert len(reaped) == 1 and reaped[0][0] == 4242 and reaped[0][1] <= before
        assert store.job(jid)['status'] == 'cancelled'
        event = store.one("SELECT data FROM events WHERE job_id=? AND kind='executors_reaped'", (jid,))
        assert json.loads(event['data'])['terminated'] == [{'pid': 21, 'name': 'node.exe'}]
        assert jid not in manager.cli_pids and jid not in manager.job_started
    asyncio.run(scenario())


def test_a_new_windows_logon_reports_startup_executors_for_review_not_as_in_flight(tmp_path):
    store, jid = task(tmp_path)
    store.status(jid, 'incomplete')
    current = sample()
    observer = WindowsHandoff(store, exclusive=True, qualified=True, probe=lambda: copy.deepcopy(current))
    async def scenario():
        await observer.begin(jid)
        # The server logged the account on again: new session id, new controller,
        # and the logon chain (shell, PowerShell, Clara) all started fresh.
        current.update(session=4, controller=[70, 900], ancestors=[69, 70])
        current['processes'] = [{'pid': 69, 'created': 899, 'name': 'powershell.exe'},
                                {'pid': 70, 'created': 900, 'name': 'python.exe'},
                                {'pid': 71, 'created': 901, 'name': 'cmd.exe'},
                                {'pid': 72, 'created': 902, 'name': 'node.exe'}]
        report = await observer.observe(jid)
        assert report['in_flight'] == []
        assert 'windows-session-or-controller-changed' in report['unknown']
        assert {'windows-process:71:901', 'windows-process:72:902'} <= set(report['unknown'])
        assert not report['complete']
        # A restarted worker in the same logon: an orphaned executor is still unfinished execution.
        current.update(session=3, controller=[70, 900], ancestors=[69, 70])
        current['processes'] = sample()['processes'] + [{'pid': 69, 'created': 899, 'name': 'powershell.exe'},
                                                        {'pid': 70, 'created': 900, 'name': 'python.exe'},
                                                        {'pid': 72, 'created': 902, 'name': 'node.exe'}]
        assert (await observer.observe(jid))['in_flight'] == ['windows-process:72:902']
    asyncio.run(scenario())


def crowded():
    """A dedicated desktop that is not empty: the operator's browser, a chat client and an old TaxPrep."""
    current = sample()
    current['shell_pid'] = 20
    current['processes'] += [{'pid': 20, 'created': 90, 'name': 'explorer.exe', 'parent': 1},
                             {'pid': 40, 'created': 150, 'name': 'chrome.exe', 'parent': 20},
                             {'pid': 41, 'created': 151, 'name': 'chrome.exe', 'parent': 40},
                             {'pid': 42, 'created': 152, 'name': 'Messenger.exe', 'parent': 20},
                             {'pid': 43, 'created': 153, 'name': 'T1Txp.exe', 'parent': 20}]
    current['windows'] += [{'handle': 40, 'pid': 40, 'class': 'Chrome_WidgetWin_1'},
                           {'handle': 42, 'pid': 42, 'class': 'TSoftrosLANMessenger'},
                           {'handle': 43, 'pid': 43, 'class': 'TaxPrep'}]
    return current


def test_programs_open_before_the_task_and_their_helpers_are_not_claras_leftovers(tmp_path):
    store, jid = task(tmp_path)
    current, clock = crowded(), [0]
    observer = WindowsHandoff(store, exclusive=True, qualified=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        assert await observer.begin(jid) == []
        saved = json.loads(store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot'])
        assert set(saved['baseline_notes']) == {'pre-existing-application-windows', 'pre-existing-task-application'}
        # The operator's browser spawns helpers for itself while Clara works; a helper's child is still the browser's.
        current['processes'] += [{'pid': 60, 'created': 300, 'name': 'chrome.exe', 'parent': 40},
                                 {'pid': 61, 'created': 301, 'name': 'chrome.exe', 'parent': 60}]
        report = await observer.observe(jid)
        assert report['unknown'] == [] and report['in_flight'] == ['windows-settling']
        clock[0] = 4
        assert (await observer.observe(jid))['complete']
        # Anything Clara's own launch chain started is hers until it ends.
        current['processes'].append({'pid': 70, 'created': 310, 'name': 'T1Txp.exe', 'parent': 10})
        report = await observer.observe(jid)
        assert 'windows-process:70:310' in report['unknown'] and not report['complete']
        current['processes'].pop()
        # A program whose launcher already exited stays hers: its parent pid is gone or reused.
        current['processes'].append({'pid': 71, 'created': 311, 'name': 'AcroRd32.exe', 'parent': 999})
        assert 'windows-process:71:311' in (await observer.observe(jid))['unknown']
        current['processes'].pop()
        # Started through the Windows shell (Start menu, Explorer): attributable to whoever clicked, so reviewed.
        current['processes'].append({'pid': 72, 'created': 312, 'name': 'WINWORD.EXE', 'parent': 20})
        assert 'windows-process:72:312' in (await observer.observe(jid))['unknown']
        current['processes'].pop()
        # A new window in a pre-existing program is still reviewed: Clara may have opened it.
        current['windows'].append({'handle': 90, 'pid': 40, 'class': 'Chrome_WidgetWin_1'})
        assert 'windows-window:90:40' in (await observer.observe(jid))['unknown']
    asyncio.run(scenario())


def test_task_started_processes_ignores_pid_reuse_and_unreadable_parents():
    baseline = crowded()
    current = copy.deepcopy(baseline)
    # pid 40 (the operator's browser) exited and Windows reused its pid for a new program Clara's tool started.
    current['processes'] = [p for p in current['processes'] if p['pid'] not in {40, 41}]
    current['processes'] += [{'pid': 40, 'created': 500, 'name': 'T1Txp.exe', 'parent': 10},
                             {'pid': 80, 'created': 501, 'name': 'AcroRd32.exe', 'parent': 40},
                             {'pid': 81, 'created': 502, 'name': 'notepad.exe'}]  # no parent field at all
    started = {p['pid'] for p in task_started_processes(current, baseline)}
    assert started == {40, 80, 81}
    # A baseline recorded by an older worker without parent identities still works on the current probe.
    old = {'processes': [{'pid': p['pid'], 'created': p['created'], 'name': p['name']} for p in baseline['processes']]}
    assert {p['pid'] for p in task_started_processes(current, old)} == {40, 80, 81}
    assert task_started_processes(current, {'baseline_issues': ['windows-baseline-unavailable']}) == current['processes']
    # Clara's launcher (pid 500) started TaxPrep and Acrobat, then was reaped; the operator's chat client
    # spawned a helper that received pid 500 afterwards. The stale pid must not make her apps foreign.
    current['processes'] += [{'pid': 70, 'created': 310, 'name': 'T1Txp.exe', 'parent': 500},
                             {'pid': 71, 'created': 311, 'name': 'AcroRd32.exe', 'parent': 500, 'parent_created': 305},
                             {'pid': 500, 'created': 400, 'name': 'Messenger.exe', 'parent': 42, 'parent_created': 152}]
    started = {p['pid'] for p in task_started_processes(current, baseline)}
    assert {70, 71} <= started and 500 not in started
    # Folder windows in a second Explorer process are still the shell: what Clara opens from them is hers.
    current['processes'] += [{'pid': 21, 'created': 91, 'name': 'explorer.exe', 'parent': 20, 'parent_created': 90},
                             {'pid': 90, 'created': 600, 'name': 'AcroRd32.exe', 'parent': 21, 'parent_created': 91}]
    baseline['processes'].append({'pid': 21, 'created': 91, 'name': 'explorer.exe', 'parent': 20})
    assert 90 in {p['pid'] for p in task_started_processes(current, baseline)}


def test_qualified_start_is_not_blocked_by_programs_someone_else_left_open(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare this T1')['local_job_id']
    manager = AgentManager(config, store)
    manager.execution_guards[jid] = lease
    manager.windows_handoff = WindowsHandoff(store, exclusive=True, qualified=True, probe=lambda: copy.deepcopy(crowded()))
    ran = []
    async def fake_execute(job, tracker, started, limit):
        ran.append(job['id'])
        store.status(job['id'], 'completed')
    manager._execute = fake_execute
    async def scenario():
        await manager.execute(store.job(jid))
        assert ran == [jid]
    asyncio.run(scenario())
    manager.windows_handoff = WindowsHandoff(store, exclusive=True, qualified=True,
                                             probe=lambda: {**crowded(), 'print_jobs': [{'queue': 'p', 'id': 1, 'status': 0}]})
    jid2 = PortalBindings(store, BASE, WORKER).persist_claim({**claim, 'job_id': str(__import__('uuid').uuid4()), 'fence_token': claim['fence_token'] + 1},
                                                              'Prepare another T1')['local_job_id']
    manager.execution_guards[jid2] = lease
    async def blocked():
        with pytest.raises(ValueError, match='No model work started'):
            await manager.execute(store.job(jid2))
    asyncio.run(blocked())
    assert ran == [jid], "Clara's own active printing still blocks a qualified start"


@pytest.mark.parametrize('parent,ok', [(0, True), (20, True), (None, False), (-1, False), (2.0, False), (True, False), ('20', False)])
def test_snapshot_parent_identity_is_a_non_negative_int_when_present(parent, ok):
    value = sample()
    validate_snapshot(copy.deepcopy(value))  # older probes report no parent at all
    value['processes'][0]['parent'] = parent
    if ok:
        validate_snapshot(value)
    else:
        with pytest.raises(ValueError, match='parent identity'):
            validate_snapshot(value)
    value['processes'][0].update(parent=20, parent_created=float('nan'))
    with pytest.raises(ValueError, match='parent identity'):
        validate_snapshot(value)


def test_general_completion_ignores_hidden_helpers_of_preexisting_programs_but_not_claras(tmp_path):
    store, jid = general_task(tmp_path)
    current, clock = crowded(), [0]
    observer = WindowsHandoff(store, exclusive=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        assert await observer.begin(jid) == []
        # Hidden helpers of the operator's browser and chat client appear while Clara works.
        current['processes'] += [{'pid': 60, 'created': 300, 'name': 'chrome.exe', 'parent': 40, 'parent_created': 150},
                                 {'pid': 61, 'created': 301, 'name': 'Messenger.exe', 'parent': 42, 'parent_created': 152}]
        assert (await observer.observe(jid))['in_flight'] == ['windows-settling']
        clock[0] = 4
        assert (await observer.observe(jid))['complete']
        # A hidden process under Clara's own launch chain is still her unfinished work.
        current['processes'].append({'pid': 62, 'created': 302, 'name': 'python.exe', 'parent': 10, 'parent_created': 110})
        report = await observer.observe(jid)
        assert report['in_flight'] == ['windows-process:62:302'] and not report['complete']
    asyncio.run(scenario())


def test_a_restarted_worker_is_not_the_finished_general_requests_unfinished_work(tmp_path):
    store, jid = general_task(tmp_path)
    current, clock = sample(), [0]
    observer = WindowsHandoff(store, exclusive=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        assert await observer.begin(jid) == []
        # Clara's service was updated and restarted after the request finished: a new
        # PowerShell and python chain now runs the observer itself.
        current.update(controller=[20, 220], ancestors=[19, 20])
        current['processes'] = [{'pid': 20, 'created': 220, 'name': 'python.exe', 'parent': 19},
                                {'pid': 19, 'created': 219, 'name': 'powershell.exe', 'parent': 1}]
        current['windows'] = [{'handle': 20, 'pid': 19, 'class': 'ConsoleWindowClass'}]
        report = await observer.observe(jid)
        assert report['in_flight'] == [], 'its own launch chain is never unfinished work'
        assert 'windows-session-or-controller-changed' in report['unknown']
        # Anything else that started with the request is still reported.
        current['processes'].append({'pid': 30, 'created': 230, 'name': 'node.exe', 'parent': 999})
        assert (await observer.observe(jid))['in_flight'] == ['windows-process:30:230']
    asyncio.run(scenario())


def test_windows_text_input_helpers_and_the_restarted_services_console_are_never_leftovers(tmp_path):
    # Observed 16 Sep 2026: typing in Softros started ctfmon/TabTip, and the service restart
    # added powershell + python + conhost + OpenConsole; all seven held the worker.
    store, jid = task(tmp_path)
    current, clock = sample(), [0]
    observer = WindowsHandoff(store, exclusive=True, qualified=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        await observer.begin(jid)
        current['processes'] += [{'pid': 24260, 'created': 300, 'name': 'ctfmon.exe'},
                                 {'pid': 81944, 'created': 300, 'name': 'TabTip.exe'},
                                 {'pid': 81776, 'created': 301, 'name': 'TabTip32.exe'}]
        assert (await observer.observe(jid))['in_flight'] == ['windows-settling'], 'text-input helpers are not work'
        # The service restarts: new launch chain powershell 11004 -> python 55648, with consoles.
        current.update(controller=[55648, 402], ancestors=[11004, 55648])
        current['processes'] += [{'pid': 11004, 'created': 401, 'name': 'powershell.exe', 'parent': 1},
                                 {'pid': 55648, 'created': 402, 'name': 'python.exe', 'parent': 11004},
                                 {'pid': 46812, 'created': 401, 'name': 'conhost.exe', 'parent': 11004},
                                 {'pid': 87272, 'created': 401, 'name': 'OpenConsole.exe', 'parent': 11004}]
        report = await observer.observe(jid)
        assert report['in_flight'] == [] and not any(r.startswith('windows-process') for r in report['unknown'])
        assert 'windows-session-or-controller-changed' in report['unknown']
        # A process the worker's own python started IS still the task's (an executor): reported.
        current['processes'].append({'pid': 60000, 'created': 500, 'name': 'node.exe', 'parent': 55648})
        report = await observer.observe(jid)
        assert 'windows-process:60000:500' in report['in_flight'] + report['unknown']
    asyncio.run(scenario())


def test_general_requests_ignore_windows_helpers_too(tmp_path):
    store, jid = general_task(tmp_path)
    current, clock = sample(), [0]
    observer = WindowsHandoff(store, exclusive=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])
    async def scenario():
        await observer.begin(jid)
        current['processes'] += [{'pid': 24260, 'created': 300, 'name': 'ctfmon.exe'},
                                 {'pid': 81944, 'created': 300, 'name': 'TabTip.exe'}]
        assert (await observer.observe(jid))['in_flight'] == ['windows-settling']
        clock[0] = 4
        assert (await observer.observe(jid))['complete']
    asyncio.run(scenario())


def test_processes_born_after_the_task_ended_are_not_its_leftovers():
    """A request that finished cannot have started a program minutes later."""
    baseline = crowded()
    current = copy.deepcopy(baseline)
    ended = 1000.0
    # Clara's own leftover: started while she worked, its launcher since reaped.
    current['processes'].append({'pid': 60, 'created': 900, 'name': 'T1Txp.exe', 'parent': 777})
    # A child that leftover spawned after the task ended is still hers.
    current['processes'].append({'pid': 61, 'created': 1400, 'name': 'AcroRd32.exe', 'parent': 60,
                                 'parent_created': 900})
    # Something unrelated that appeared long afterwards, launcher already gone.
    current['processes'].append({'pid': 62, 'created': 1500, 'name': 'Updater.exe', 'parent': 888})
    # And its own child, equally unrelated.
    current['processes'].append({'pid': 63, 'created': 1600, 'name': 'Helper.exe', 'parent': 62,
                                 'parent_created': 1500})
    started = {p['pid'] for p in task_started_processes(current, baseline, ended)}
    assert started == {60, 61}
    # Inside the grace, the end of a task and its last action are the same moment.
    edge = copy.deepcopy(baseline)
    edge['processes'].append({'pid': 64, 'created': ended + 5, 'name': 'T1Txp.exe', 'parent': 777})
    assert 64 in {p['pid'] for p in task_started_processes(edge, baseline, ended)}
    # While the task is still running nothing is excluded by time.
    assert {p['pid'] for p in task_started_processes(current, baseline, None)} == {60, 61, 62, 63}


def test_finished_general_request_is_released_despite_a_later_unrelated_process(tmp_path):
    """The exact Softros case: a background program appeared an hour after the request."""
    store, jid = general_task(tmp_path)
    current, clock = crowded(), [0]
    observer = WindowsHandoff(store, exclusive=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])

    async def scenario():
        assert await observer.begin(jid) == []
        ended = store.job(jid)['finished']
        assert (await observer.observe_general(jid))['in_flight'] == ['windows-settling']
        clock[0] = 4
        assert (await observer.observe_general(jid))['complete']
        # An invisible program whose launcher has exited turns up an hour later.
        current['processes'].append({'pid': 103796, 'created': ended + 3600, 'name': 'Updater.exe',
                                     'parent': 424242})
        report = await observer.observe_general(jid)
        assert report['in_flight'] == [] and report['complete']
        # Something Clara started during the request still holds the worker.
        current['processes'].append({'pid': 103797, 'created': ended - 60, 'name': 'Messenger.exe',
                                     'parent': 424243})
        assert f"windows-process:103797:{ended - 60}" in (await observer.observe_general(jid))['in_flight']
    asyncio.run(scenario())


def test_a_tax_application_s_own_updater_is_not_a_leftover(tmp_path):
    """Launching ProFile spawns Intuit's updater; it held the worker after a clean run."""
    store, jid = general_task(tmp_path)
    current, clock = crowded(), [0]
    observer = WindowsHandoff(store, exclusive=True, probe=lambda: copy.deepcopy(current), clock=lambda: clock[0])

    async def scenario():
        assert await observer.begin(jid) == []
        assert (await observer.observe_general(jid))['in_flight'] == ['windows-settling']
        clock[0] = 4
        assert (await observer.observe_general(jid))['complete']
        # ProFile starts its own background updater when Clara launches it.
        current['processes'].append({'pid': 9520, 'created': 400, 'parent': 777,
                                     'name': 'Intuit.PCG.ProFile.AutoUpdate.exe'})
        report = await observer.observe_general(jid)
        assert report['in_flight'] == [] and report['complete'], 'the vendor updater must not hold the worker'
        # Anything Clara really left running still does.
        current['processes'].append({'pid': 9521, 'created': 401, 'parent': 777, 'name': 'ProFile.exe'})
        assert 'windows-process:9521:401' in (await observer.observe_general(jid))['in_flight']
    asyncio.run(scenario())
