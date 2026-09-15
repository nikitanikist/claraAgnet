import asyncio
import copy
from dataclasses import asdict
import json
import time

import pytest

from clara.portal_bindings import PortalBindings
from clara.portal_journal import PortalJournal
from clara.agent import AgentManager
from clara.portal_windows import WindowsHandoff, validate_snapshot, baseline_issues
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


@pytest.mark.parametrize('blocked', ['unqualified', 'shared', 'missing-baseline', 'interrupted', 'no-receipt', 'dirty-baseline'])
def test_operator_or_task_preconditions_cannot_be_replaced_by_a_quiet_desktop(tmp_path, blocked):
    store, jid = task(tmp_path)
    current = sample()
    if blocked == 'dirty-baseline':
        current['processes'].append({'pid': 55, 'created': 200, 'name': 'T1Txp.exe'})
    observer = WindowsHandoff(store, exclusive=blocked != 'shared', qualified=blocked != 'unqualified',
                              probe=lambda: copy.deepcopy(current))
    async def scenario():
        if blocked != 'missing-baseline':
            await observer.begin(jid)
        if blocked == 'interrupted':
            store.status(jid, 'interrupted')
        if blocked == 'no-receipt':
            store.execute("DELETE FROM portal_v1_outbox WHERE operation='clara-result'")
        if blocked == 'dirty-baseline':
            current['processes'].pop()
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


def test_failed_restart_reviews_apps_without_counting_current_worker_as_old_execution(tmp_path):
    store, jid = task(tmp_path)
    store.status(jid, 'failed')
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
        assert {'windows-process:30:230', 'windows-process:31:231',
                'windows-window:30:30', 'windows-session-or-controller-changed',
                'windows-interrupted-task-needs-review', 'windows-handoff-not-qualified'} <= set(report['unknown'])
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


def test_shell_helpers_require_actual_shell_pid_and_explorer_folders_still_block():
    current = sample()
    current['shell_pid'] = 20
    current['windows'] += [{'handle': 88, 'pid': 20, 'class': 'ThumbnailDeviceHelperWnd'},
                           {'handle': 89, 'pid': 20, 'class': 'EdgeUiInputTopWndClass'}]
    assert baseline_issues(current) == []
    current['windows'].append({'handle': 90, 'pid': 20, 'class': 'CabinetWClass'})
    assert 'windows-baseline-applications-open' in baseline_issues(current)
    current['windows'].pop()
    current['windows'][1]['pid'] = 30
    assert 'windows-baseline-applications-open' in baseline_issues(current)


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
