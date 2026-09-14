import asyncio
import json
import time

import httpx
import pytest

from clara.agent import AgentManager
from clara.portal_bindings import PortalBindings
from clara.portal_intake import PreparedAttempt
from clara.portal_journal import PortalJournal
from clara.portal_lease import LeaseLost
from clara.portal_session import PortalSession
from clara.portal_transport import PortalTransport
from test_portal_delivery import BASE, WORKER, CONTRACT, setup, wire


def environment(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    row = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Assigned task.')
    manager = AgentManager(config, store)
    assert manager.reserve_execution('portal')
    return store, manager, PreparedAttempt(row['local_job_id'], lease, False)


def test_stop_is_delivered_while_chat_receipt_is_blocked(tmp_path):
    async def scenario():
        store, manager, prepared = environment(tmp_path)
        jid = prepared.local_job_id
        store.event(store.job(jid)['conversation_id'], jid, 'assistant', {'text': 'Checking the assigned files.'})
        chat_started, chat_cancelled = asyncio.Event(), asyncio.Event()
        acked = []
        async def handle(request):
            op = request.url.path.rsplit('/', 1)[-1]
            if op == 'clara-heartbeat':
                return wire(CONTRACT.document['fixtures'][op]['response'])
            if op == 'clara-chat':
                chat_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    chat_cancelled.set()
            if op == 'clara-commands':
                await chat_started.wait()
                return wire({'commands': [{'command_id': 1, 'type': 'stop', 'reason': 'Operator stopped work',
                    'issued_at': '2026-09-14T00:00:00Z'}], 'server_time': '2026-09-14T00:00:00Z'})
            if op == 'clara-command-ack':
                acked.append(json.loads(request.content))
                return wire({'command_id': 1, 'recorded': True, 'server_time': '2026-09-14T00:00:00Z'})
            raise AssertionError(op)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            transport = PortalTransport(BASE, lambda: 'test-key', client=client, clock=lambda: 100)
            session = PortalSession(store, manager, transport, PortalJournal(store, BASE), prepared)
            session.start()
            job = await asyncio.wait_for(session.wait_for_execution(), 1)
            assert job['status'] == 'cancelled'
            assert acked[0]['status'] == 'accepted'
            assert not chat_cancelled.is_set()
            assert manager.execution_reservation == 'portal'
            await session.close()
            assert chat_cancelled.is_set()
            assert all(t.done() for t in session.tasks)
    asyncio.run(scenario())


def test_lease_watchdog_stops_even_when_every_http_request_hangs(tmp_path):
    async def scenario():
        store, manager, prepared = environment(tmp_path)
        prepared.lease.clock = time.monotonic
        async def handle(request):
            await asyncio.Event().wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            session = PortalSession(store, manager,
                PortalTransport(BASE, lambda: 'test-key', client=client), PortalJournal(store, BASE), prepared)
            prepared.lease.deadline = time.monotonic() + 0.05
            session.start()
            job = await asyncio.wait_for(session.wait_for_execution(), 1)
            assert job['status'] == 'cancelled'
            with pytest.raises(LeaseLost):
                prepared.lease.assert_active()
            assert manager.execution_reservation == 'portal'
            await session.close()
            assert all(t.done() for t in session.tasks)
    asyncio.run(scenario())


def test_local_completion_keeps_connection_and_reservation_for_result_delivery(tmp_path):
    async def scenario():
        store, manager, prepared = environment(tmp_path)
        store.status(prepared.local_job_id, 'completed')
        async def handle(request):
            await asyncio.Event().wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            session = PortalSession(store, manager,
                PortalTransport(BASE, lambda: 'test-key', client=client), PortalJournal(store, BASE), prepared)
            session.start()
            job = await session.wait_for_execution()
            assert job['status'] == 'completed'
            assert not session.closed and all(not t.done() for t in session.tasks)
            prepared.lease.assert_active()
            await session.close()
            assert store.job(prepared.local_job_id)['status'] == 'completed'
            assert manager.execution_reservation == 'portal'
    asyncio.run(scenario())
