import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from clara.agent import AgentManager
from clara.config import Config
from clara.portal_bindings import PortalBindings
from clara.portal_contract import ContractViolation, PortalContract
from clara.portal_delivery import PortalDelivery
from clara.portal_lease import AttemptIdentity, ExecutionLease
from clara.portal_transport import PortalTransport, PortalUnavailable
from clara.store import Store


BASE = 'https://example.supabase.co/functions/v1'
WORKER = '22222222-2222-4222-8222-222222222222'
CONTRACT = PortalContract.bundled()


def setup(tmp_path):
    config = Config(tmp_path / 'data')
    config.initialize()
    store = Store(config.data / 'db')
    claim = copy.deepcopy(CONTRACT.document['fixtures']['clara-claim']['response'])
    identity = AttemptIdentity(claim['job_id'], WORKER, claim['attempt_no'], claim['fence_token'])
    lease = ExecutionLease(identity, clock=lambda: 100)
    server = datetime(2026, 9, 14, tzinfo=timezone.utc)
    lease.acknowledge(identity, server_time=server, expires_at=server+timedelta(seconds=120), request_started=100)
    return config, store, claim, lease


def wire(body):
    return httpx.Response(200, json=body, headers={'x-clara-contract': '1'})


def handler_for(claim, calls, *, lose_ack=False, bad_page=None):
    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path.rsplit('/', 1)[-1], body))
        if request.url.path.endswith('clara-message-ack'):
            if lose_ack and sum(c[0]=='clara-message-ack' for c in calls)==1:
                raise httpx.ReadError('lost receipt', request=request)
            return wire({**CONTRACT.document['fixtures']['clara-message-ack']['response']})
        seq = body['after_seq'] + 1
        message = {**claim['messages'][0], 'seq': seq,
                   'message_id': f'55555555-5555-4555-8555-{seq:012d}'}
        page = {**CONTRACT.document['fixtures']['clara-messages']['response'],
                'messages': [message], 'more_messages': seq < claim['message_boundary_seq']}
        if bad_page:
            page.update(bad_page)
        return wire(page)
    return handle


def test_all_pages_and_ack_are_required_before_exactly_once_enqueue(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    calls = []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(claim, calls))) as client:
            transport = PortalTransport(BASE, lambda: 'test-key', client=client)
            delivery = PortalDelivery(store, transport)
            manager = AgentManager(config, store)
            assert manager.reserve_execution('portal')
            messages = await delivery.receive(claim, lease)
            assert [m['seq'] for m in messages] == [11, 12]
            assert store.rows('SELECT * FROM jobs') == []
            row = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare the assigned task.')
            jid = row['local_job_id']
            with pytest.raises(ValueError, match='acknowledge'):
                manager.enqueue_portal_job(jid, reservation_id='portal', execution_guard=lease)
            assert manager.queue.empty()
            await delivery.acknowledge(lease)
            manager.enqueue_portal_job(jid, reservation_id='portal', execution_guard=lease)
            assert manager.queue.get_nowait() == jid
            with pytest.raises(ValueError, match='already dispatched'):
                manager.enqueue_portal_job(jid, reservation_id='portal', execution_guard=lease)
            assert manager.queue.empty()
            assert [c[0] for c in calls] == ['clara-messages', 'clara-messages', 'clara-message-ack']
    asyncio.run(scenario())


def test_lost_ack_retries_saved_window_without_replaying_execution(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    calls = []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(claim, calls, lose_ack=True))) as client:
            transport = PortalTransport(BASE, lambda: 'test-key', client=client)
            delivery = PortalDelivery(store, transport)
            messages = await delivery.receive(claim, lease)
            row = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare assigned task.')
            with pytest.raises(PortalUnavailable):
                await delivery.acknowledge(lease)
            reopened = Store(store.path)
            reopened.recover()
            delivery = PortalDelivery(reopened, transport)
            assert await delivery.receive({**claim, 'recovered': True}, lease) == messages
            assert PortalBindings(reopened, BASE, WORKER).persist_claim({**claim, 'recovered': True}, 'Do not restart')['created_now'] is False
            await delivery.acknowledge(lease)
            assert len([c for c in calls if c[0]=='clara-messages']) == 2
            assert calls[-1] == calls[-2]
            manager = AgentManager(config, reopened)
            assert manager.reserve_execution('recovery')
            with pytest.raises(ValueError):
                manager.enqueue_portal_job(row['local_job_id'], reservation_id='recovery', execution_guard=lease)
            assert manager.queue.empty()
    asyncio.run(scenario())


@pytest.mark.parametrize('bad_page', [
    {'to_seq': 13}, {'messages': []}, {'more_messages': False},
])
def test_incomplete_or_changed_window_never_acknowledges_or_creates_work(tmp_path, bad_page):
    _, store, claim, lease = setup(tmp_path)
    calls = []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(claim, calls, bad_page=bad_page))) as client:
            delivery = PortalDelivery(store, PortalTransport(BASE, lambda: 'test-key', client=client))
            with pytest.raises((ContractViolation, PortalUnavailable)):
                await delivery.receive(claim, lease)
            assert store.rows('SELECT * FROM jobs') == []
            assert store.rows('SELECT * FROM portal_v1_deliveries') == []
            assert all(c[0] != 'clara-message-ack' for c in calls)
    asyncio.run(scenario())
