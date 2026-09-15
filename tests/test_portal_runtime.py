import asyncio
import copy
import json
import time
from uuid import uuid4

import httpx
import pytest

from clara.agent import AgentManager
from clara.portal_runtime import PortalRuntime
from clara.portal_bindings import PortalBindings
from clara.portal_transport import PortalTransport
from clara.store import Store
from test_portal_delivery import BASE, CONTRACT, WORKER, setup, wire, handler_for


def general(claim):
    claim.update(kind='general', closeout=None, required_outputs=[])
    claim['scope']['closeout_form_id'] = None
    claim['scope']['permissions'] = ['general']
    return claim


@pytest.mark.parametrize('unreturned', [False, True])
def test_windows_quiet_observation_does_not_clear_other_unresolved_calls(tmp_path, unreturned):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    executions, calls = [], []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls))) as client:
            manager = simulated_manager(config, store, executions, desktop=True)
            previous_execute = manager.execute
            async def execute(job):
                await previous_execute(job)
                if unreturned:
                    store.event(job['conversation_id'], job['id'], 'tool', {'id':'unreturned', 'name':'Read'})
            manager.execute = execute
            class Observer:
                async def observe(self, jid):
                    return {'in_flight':[], 'unknown':[], 'complete':True}
            manager.windows_handoff = Observer()
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                outcome = await asyncio.wait_for(runtime.tick(), 3)
                report = next(b['report'] for op,b in calls if op == 'clara-quiesce')
                assert 'external-desktop-state-unconfirmed' not in report['unknown']
                assert report['complete'] is (not unreturned)
                assert outcome == ('held' if unreturned else 'finished')
                assert bool(manager.execution_reservation) is unreturned
                assert len(executions) == 1
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def portal_handler(claim, calls, *, result_losses=0, claim_losses=0):
    results, claims = 0, 0
    def handle(request):
        nonlocal results, claims
        op = request.url.path.rsplit('/', 1)[-1]
        body = json.loads(request.content)
        calls.append((op, body))
        if op == 'clara-claim':
            claims += 1
            if claims <= claim_losses:
                raise httpx.ReadError('Lost claim receipt', request=request)
            return wire({**claim, 'recovered':claims > 1})
        if op in {'clara-messages', 'clara-message-ack'}:
            return handler_for(claim, [])(request)
        if op == 'clara-commands':
            return wire({'commands':[], 'server_time':'2026-09-14T00:00:00Z'})
        if op == 'clara-events':
            return wire({**CONTRACT.document['fixtures'][op]['response'],
                         'accepted_uids':[e['event_uid'] for e in body['events']], 'duplicate_uids':[]})
        if op == 'clara-result':
            results += 1
            if results <= result_losses:
                raise httpx.ReadError('Lost result receipt', request=request)
        if op == 'clara-quiesce':
            quiet = body['report']['complete']
            return wire({'quiescent':quiet, 'recovery_hold':not quiet,
                         'released_locks':[], 'server_time':'2026-09-14T00:00:00Z'})
        return wire(CONTRACT.document['fixtures'][op]['response'])
    return handle


def simulated_manager(config, store, executions, *, desktop=False):
    manager = AgentManager(config, store)
    async def execute(job):
        manager.assert_execution_permitted(job)
        executions.append(job['id'])
        store.status(job['id'], 'running')
        if desktop:
            for kind in ('tool', 'tool_done'):
                store.event(job['conversation_id'], job['id'], kind,
                            {'id':'simulated-click', 'name':'mcp__chrome__click'})
        # Enough local-only events to require several final progress batches.
        for i in range(230):
            store.event(job['conversation_id'], job['id'], 'diagnostic', {'index':i})
        store.event(job['conversation_id'], job['id'], 'assistant', {'text':'The requested file path is available.'})
        store.status(job['id'], 'completed')
    manager.execute = execute
    return manager


def test_serial_cycle_drains_final_progress_then_reports_before_releasing_slot(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    executions, calls = [], []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await asyncio.wait_for(runtime.tick(), 3) == 'finished'
                assert len(executions) == 1
                assert manager.execution_reservation is None and runtime.pending() is None
                ops = [op for op, _ in calls]
                assert ops.index('clara-message-ack') < ops.index('clara-chat') < ops.index('clara-result') < ops.index('clara-quiesce')
                assert next(b for op,b in calls if op == 'clara-chat')['body'] == 'The requested file path is available.'
                cursor = store.one('SELECT event_id FROM portal_v1_progress')['event_id']
                assert cursor == store.one('SELECT max(id) AS id FROM events')['id']
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_lost_result_receipt_recovers_after_restart_without_another_claim_or_execution(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    executions, calls = [], []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls, result_losses=1))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            assert await asyncio.wait_for(runtime.tick(), 3) == 'held'
            assert runtime.pending()['local_job_id'] == executions[0]
            assert manager.execution_reservation
            await runtime.close()
            await manager.close()
            reopened = Store(store.path)
            manager = simulated_manager(config, reopened, executions)
            await manager.start()
            runtime = PortalRuntime(config, reopened, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await runtime.tick() == 'finished'
                assert len(executions) == 1
                assert len([c for c in calls if c[0] == 'clara-claim']) == 1
                results = [b for op,b in calls if op == 'clara-result']
                assert len(results) == 2 and results[0] == results[1]
                assert manager.execution_reservation is None
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_lost_claim_receipt_keeps_local_reservation_and_recovers_same_claim(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    executions, calls = [], []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls, claim_losses=1))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await runtime.tick() == 'claim_unknown'
                reserved = manager.execution_reservation
                assert reserved and not executions
                assert runtime.pending()['claim_json'] is None
                assert await runtime.tick() == 'finished'
                assert len(executions) == 1 and len(store.rows('SELECT id FROM portal_v1_cycles')) == 1
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_returned_desktop_call_does_not_release_worker_or_start_another_task(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    executions, calls = [], []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls))) as client:
            manager = simulated_manager(config, store, executions, desktop=True)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await runtime.tick() == 'held'
                assert await runtime.tick() == 'held'
                assert manager.execution_reservation and len(executions) == 1
                # Polling a recovered copy of the OLD claim never authorizes
                # replay or releases the saved reservation.
                assert len([c for c in calls if c[0] == 'clara-claim']) == 3
                assert len(store.rows('SELECT id FROM portal_v1_cycles')) == 1
                reports = [b for op,b in calls if op == 'clara-quiesce']
                assert len(reports) == 1
                assert reports[0]['report']['unknown'] == ['external-desktop-state-unconfirmed']
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_stop_during_blocked_intake_prevents_ack_and_execution(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    calls, executions = [], []
    async def scenario():
        receiving, cancelled = asyncio.Event(), asyncio.Event()
        async def handle(request):
            op = request.url.path.rsplit('/', 1)[-1]
            calls.append(op)
            if op == 'clara-claim':
                return wire(claim)
            if op == 'clara-messages':
                receiving.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            if op == 'clara-heartbeat':
                await receiving.wait()
                return wire({**CONTRACT.document['fixtures'][op]['response'], 'stop_requested':True})
            if op == 'clara-quiesce':
                report = json.loads(request.content)['report']
                assert report['complete'] and report['finished'] == ['intake:no-execution']
                return wire({'quiescent':True, 'recovery_hold':False, 'released_locks':[],
                             'server_time':'2026-09-14T00:00:00Z'})
            raise AssertionError(op)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await asyncio.wait_for(runtime.tick(), 2) == 'held'
                assert cancelled.is_set() and not executions
                assert store.rows('SELECT id FROM jobs') == []
                assert 'clara-message-ack' not in calls and manager.execution_reservation
                assert await runtime.tick() == 'finished'
                assert 'clara-result' not in calls and manager.execution_reservation is None
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('flags,released', [
    ({'attempt_released':True, 'recovery_hold':False}, True),
    ({'attempt_released':False, 'recovery_hold':True}, False),
    ({'attempt_released':True, 'recovery_hold':True}, False),
    ({'attempt_released':False, 'recovery_hold':False}, False),
    ({}, False),
])
def test_context_delivery_failure_releases_only_on_an_unambiguous_receipt(tmp_path, flags, released):
    config, store, _, _ = setup(tmp_path)
    calls, executions = [], []
    def handle(request):
        calls.append(request.url.path)
        return wire({'claimed':False, 'reason':'context_unavailable',
                     'heartbeat_interval_s':10, 'server_time':'2026-09-14T00:00:00Z', **flags})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await runtime.tick() == ('idle' if released else 'held')
                assert (manager.execution_reservation is None) == released
                assert not executions and len(calls) == 1
                if not released:
                    assert await runtime.tick() == 'held'
                    assert len(calls) == 1
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('unconfirmed', [False, True])
def test_interrupted_attempt_without_result_reports_inventory_without_replaying(tmp_path, unconfirmed):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Synthetic interrupted task')['local_job_id']
    cid = store.job(jid)['conversation_id']
    store.status(jid, 'interrupted')
    if unconfirmed:
        store.event(cid, jid, 'tool', {'id':'uncertain-print', 'name':'mcp__windows__Click'})
    cycle_id = str(uuid4())
    store.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                  (cycle_id, BASE, WORKER, 'held', json.dumps(claim), jid, time.time()))
    calls, executions = [], []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await runtime.tick() == ('held' if unconfirmed else 'finished')
                assert not executions
                assert [op for op,_ in calls] == ['clara-quiesce'] + (['clara-claim'] if unconfirmed else [])
                report = calls[0][1]['report']
                assert report['complete'] == (not unconfirmed)
                assert (manager.execution_reservation is not None) == unconfirmed
                if unconfirmed:
                    assert 'tool:uncertain-print' in report['unknown']
                assert store.job(jid)['usage'] is None
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('lose_receipt', [False, True])
def test_operator_reconciliation_accepts_only_a_new_attempt_and_keeps_previous_work(tmp_path, lose_receipt):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Original interrupted task')['local_job_id']
    cid = store.job(jid)['conversation_id']
    store.status(jid, 'interrupted')
    store.event(cid, jid, 'tool', {'id':'uncertain-print', 'name':'mcp__windows__Click'})
    cycle_id = str(uuid4())
    store.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                  (cycle_id, BASE, WORKER, 'held', json.dumps(claim), jid, time.time()))
    newer = copy.deepcopy(claim)
    newer.update(attempt_no=claim['attempt_no'] + 1, fence_token=claim['fence_token'] + 1,
                 execution_id=str(uuid4()))
    calls, executions = [], []
    original_handler = portal_handler(newer, calls)
    reconciled, issued = False, False
    def handle(request):
        nonlocal issued
        if request.url.path.endswith('clara-claim'):
            if not reconciled:
                return wire({'claimed':False, 'reason':'recovery_hold', 'recovery_hold':True,
                             'heartbeat_interval_s':10, 'server_time':'2026-09-14T00:00:00Z'})
            if lose_receipt and not issued:
                issued = True
                raise httpx.ReadError('Lost newer claim receipt', request=request)
        return original_handler(request)
    async def scenario():
        nonlocal reconciled
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            try:
                assert await runtime.tick() == 'held'
                assert not executions and manager.execution_reservation == cycle_id
                reconciled = True  # Portal operator resolved the recorded actions.
                if lose_receipt:
                    assert await runtime.tick() == 'held'
                    assert not executions and manager.execution_reservation == cycle_id
                assert await runtime.tick() == 'finished'
                assert len(executions) == 1 and executions[0] != jid
                assert store.job(executions[0])['conversation_id'] == cid
                assert store.job(jid)['status'] == 'interrupted'
                assert store.one('SELECT state FROM portal_v1_cycles WHERE id=?', (cycle_id,))['state'] == 'reconciled'
                assert len(store.rows('SELECT id FROM portal_v1_cycles')) == 2
                assert len(store.rows('SELECT local_job_id FROM portal_v1_attempts')) == 2
                assert store.job(jid)['usage'] is None
                assert manager.execution_reservation is None
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_held_cycle_with_in_flight_work_announces_presence_once_per_interval(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Synthetic interrupted task')['local_job_id']
    store.status(jid, 'interrupted')
    cycle_id = str(uuid4())
    store.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                  (cycle_id, BASE, WORKER, 'held', json.dumps(claim), jid, time.time()))
    def observer(store, manager, namespace, identity, local_job_id):
        return {'finished':[], 'in_flight':['tool:printing'], 'unknown':[],
                'observed_at':'2026-09-14T00:00:00Z', 'complete':False}
    calls, executions, now = [], [], [100]
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:now[0]), WORKER, observer=observer)
            try:
                # The fixture heartbeat response advertises a 20 s interval.
                for tick, expected in [(100, 1), (110, 1), (121, 2), (130, 2), (141, 3)]:
                    now[0] = tick
                    assert await runtime.poll() == 'held'
                    assert len([b for op,b in calls if op == 'clara-heartbeat']) == expected
                beats = [b for op,b in calls if op == 'clara-heartbeat']
                assert all(b == {'worker_id':WORKER, 'busy':False} for b in beats)
                assert 'clara-claim' not in [op for op,_ in calls]
                assert not executions and manager.execution_reservation == cycle_id
                assert runtime.pending()['state'] == 'held'
                assert 'unconfirmed' in runtime.error
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def held_in_flight_cycle(store, claim):
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Synthetic interrupted task')['local_job_id']
    store.status(jid, 'interrupted')
    cycle_id = str(uuid4())
    store.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                  (cycle_id, BASE, WORKER, 'held', json.dumps(claim), jid, time.time()))
    return cycle_id


def in_flight_observer(store, manager, namespace, identity, local_job_id):
    return {'finished':[], 'in_flight':['tool:printing'], 'unknown':[],
            'observed_at':'2026-09-14T00:00:00Z', 'complete':False}


def test_presence_interval_is_capped_at_two_minutes(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    cycle_id = held_in_flight_cycle(store, claim)
    calls, executions, now = [], [], [100]
    original_handler = portal_handler(claim, calls)
    def handle(request):
        if request.url.path.endswith('clara-heartbeat'):
            calls.append(('clara-heartbeat', json.loads(request.content)))
            return wire({**CONTRACT.document['fixtures']['clara-heartbeat']['response'], 'heartbeat_interval_s':3600})
        return original_handler(request)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:now[0]), WORKER, observer=in_flight_observer)
            try:
                for tick, expected in [(100, 1), (159, 1), (219, 1), (220, 2), (339, 2), (340, 3)]:
                    now[0] = tick
                    assert await runtime.poll() == 'held'
                    assert len([b for op,b in calls if op == 'clara-heartbeat']) == expected
                assert not executions and manager.execution_reservation == cycle_id
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_presence_failure_with_a_value_error_leaves_the_held_error_alone(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    cycle_id = held_in_flight_cycle(store, claim)
    calls, executions = [], []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(portal_handler(claim, calls))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            transport = PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100)
            original_request = transport.request
            async def request(operation, payload, **kw):
                if operation == 'clara-heartbeat':
                    raise ValueError('The configured portal worker credential is unavailable.')
                return await original_request(operation, payload, **kw)
            transport.request = request
            runtime = PortalRuntime(config, store, manager, transport, WORKER, observer=in_flight_observer)
            try:
                assert await runtime.poll() == 'held'
                assert 'unconfirmed' in runtime.error and 'credential' not in runtime.error
                assert runtime.pending()['state'] == 'held' and runtime.pending()['error'] == runtime.error
                assert manager.execution_reservation == cycle_id and not executions
                assert 'clara-heartbeat' not in [op for op,_ in calls]
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_unexpected_os_error_logs_no_file_name_or_path(tmp_path):
    config, store, _, _ = setup(tmp_path)
    executions = []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: wire({}))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            async def broken():
                raise FileNotFoundError(2, 'No such file or directory', '/Users/clara/Clients/Smith Family/2025 T1 Return.pdf')
            runtime.tick = broken
            try:
                await runtime.start()
                async with asyncio.timeout(3):
                    while runtime.error is None:
                        await asyncio.sleep(0.01)
                assert runtime.error.endswith('(FileNotFoundError)')
                lines = (config.data / 'logs' / 'portal-runtime.log').read_text().splitlines()
                assert len(lines) == 1 and ' FileNotFoundError errno=2 No such file or directory' in lines[0]
                assert not any(part in lines[0] for part in ('/Users', 'Clients', 'Smith', 'T1 Return', '.pdf'))
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('text', [
    "Cannot open '/Users/clara/Clients/Smith/T1.pdf' for the report",
    'Cannot open C:\\Users\\clara\\Clients\\Smith\\T1.pdf for the report',
    'Cannot open \\\\server\\share\\Smith\\T1.pdf for the report',
    'Cannot open "Clients\\Smith\\T1.pdf" for the report',
    'Cannot open /Users/clara/Clients/Smith/T1.pdf for the report'])
def test_diagnose_masks_path_like_tokens(tmp_path, text):
    config, store, _, _ = setup(tmp_path)
    runtime = PortalRuntime(config, store, None, PortalTransport(BASE, lambda:'test', client=httpx.AsyncClient()), WORKER)
    runtime._diagnose(RuntimeError(text))
    line = (config.data / 'logs' / 'portal-runtime.log').read_text()
    assert line.endswith(' RuntimeError Cannot open [path] for the report\n')
    assert 'Smith' not in line and 'T1.pdf' not in line


@pytest.mark.parametrize('answer,outcome', [('released', 'idle'), ('hold', 'held'), ('claimed', 'finished')])
def test_held_cycle_without_claim_retries_the_claim_after_thirty_seconds(tmp_path, answer, outcome):
    config, store, claim, _ = setup(tmp_path)
    general(claim)
    cycle_id = str(uuid4())
    store.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,NULL,NULL,?,NULL,?)',
                  (cycle_id, BASE, WORKER, 'held', time.time(), 'The portal rejected the claim.'))
    calls, executions, now = [], [], [100]
    original_handler = portal_handler(claim, calls)
    def handle(request):
        if request.url.path.endswith('clara-claim') and answer != 'claimed':
            calls.append(('clara-claim', json.loads(request.content)))
            hold = {'reason':'recovery_hold', 'recovery_hold':True} if answer == 'hold' else {'reason':'no_work'}
            return wire({'claimed':False, 'heartbeat_interval_s':10, 'server_time':'2026-09-14T00:00:00Z', **hold})
        return original_handler(request)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:now[0]), WORKER)
            try:
                for now[0] in (100, 115, 129):
                    assert await runtime.tick() == 'held'
                assert calls == [] and manager.execution_reservation == cycle_id
                now[0] = 130
                assert await asyncio.wait_for(runtime.tick(), 3) == outcome
                claims = [b for op,b in calls if op == 'clara-claim']
                assert len(claims) == 1 and claims[0]['worker_id'] == WORKER
                cycle = store.one('SELECT * FROM portal_v1_cycles WHERE id=?', (cycle_id,))
                if answer == 'released':
                    assert cycle['state'] == 'finished' and cycle['finished'] and cycle['error'] is None
                    assert manager.execution_reservation is None and not executions
                elif answer == 'hold':
                    assert cycle['state'] == 'held' and cycle['finished'] is None
                    assert 'existing worker hold' in cycle['error'] and runtime.error == cycle['error']
                    assert manager.execution_reservation == cycle_id and not executions
                    now[0] = 145
                    assert await runtime.tick() == 'held' and len(calls) == 1
                    now[0] = 160
                    assert await runtime.tick() == 'held' and len(calls) == 2
                else:
                    assert cycle['state'] == 'finished' and json.loads(cycle['claim_json'])['job_id'] == claim['job_id']
                    assert len(executions) == 1 and manager.execution_reservation is None
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())


def test_unexpected_runtime_exception_logs_a_redacted_line_and_names_the_class(tmp_path):
    config, store, _, _ = setup(tmp_path)
    executions = []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: wire({}))) as client:
            manager = simulated_manager(config, store, executions)
            await manager.start()
            runtime = PortalRuntime(config, store, manager,
                PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100), WORKER)
            async def broken():
                raise RuntimeError('Authorization: Bearer SECRETBEARER1 key sk-ant-SECRETKEY0123456789 '
                                   'https://example.supabase.co/functions/v1/x?token=SECRETQUERY\nline two')
            runtime.tick = broken
            try:
                await runtime.start()
                async with asyncio.timeout(3):
                    while runtime.error is None:
                        await asyncio.sleep(0.01)
                assert runtime.error == ('Portal work needs review. Existing work and the worker hold have been preserved. (RuntimeError)')
                assert 'Traceback' not in runtime.error and 'SECRET' not in runtime.error
                lines = (config.data / 'logs' / 'portal-runtime.log').read_text().splitlines()
                assert len(lines) == 1 and ' RuntimeError ' in lines[0]
                assert lines[0].startswith('20') and 'SECRET' not in lines[0] and 'line two' in lines[0]
                assert not executions
            finally:
                await runtime.close()
                await manager.close()
    asyncio.run(scenario())
