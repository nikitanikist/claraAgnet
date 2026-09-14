import asyncio
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
                assert len([c for c in calls if c[0] == 'clara-claim']) == 1
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
                assert not executions and [op for op,_ in calls] == ['clara-quiesce']
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
