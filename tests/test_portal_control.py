import asyncio
import copy
import json

import httpx
import pytest

from clara.agent import AgentManager
from clara.portal_bindings import PortalBindings
from clara.portal_control import PortalControl
from clara.portal_journal import PortalJournal
from clara.portal_lease import LeaseLost
from clara.portal_transport import PortalTransport, PortalUnavailable
from test_portal_delivery import BASE, WORKER, CONTRACT, setup, wire


def answer():
    return copy.deepcopy(CONTRACT.document['fixtures']['clara-commands']['response']['commands'][0])


def environment(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    row = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Assigned task.')
    manager = AgentManager(config, store)
    jid = row['local_job_id']
    future = asyncio.get_running_loop().create_future()
    manager.pending['req_7'] = {'job_id': jid, 'conversation_id': store.job(jid)['conversation_id'],
        'kind': 'question', 'data': {'question': 'Which folder?', 'context': 'Choose the destination.',
            'details': 'Long optional details.', 'choices': [{'label': 'Test folder', 'answer': 'Use the dedicated test folder only.'}]},
        'future': future}
    return store, manager, lease, jid, future


def test_stop_precedes_simultaneous_answer(tmp_path):
    async def scenario():
        store, manager, lease, jid, future = environment(tmp_path)
        a = answer()
        stop = {'command_id': 43, 'type': 'stop', 'reason': 'Stopped by staff', 'issued_at': a['issued_at']}
        acks = []
        def handle(request):
            if request.url.path.endswith('clara-commands'):
                return wire({'commands': [a, stop], 'server_time': a['issued_at']})
            body = json.loads(request.content)
            acks.append(body)
            return wire({'command_id': body['command_id'], 'recorded': True, 'server_time': a['issued_at']})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            control = PortalControl(store, manager, PortalTransport(BASE, lambda: 'test-key', client=client),
                                    PortalJournal(store, BASE), lease, jid)
            await control.poll_commands()
            assert not future.done()
            with pytest.raises(LeaseLost):
                lease.assert_active()
            assert [(v['command_id'], v['status']) for v in acks] == [(43, 'accepted'), (42, 'expired')]
            assert store.job(jid)['status'] == 'cancelled'
    asyncio.run(scenario())


def test_answer_maps_choice_and_lost_receipt_does_not_deliver_twice(tmp_path):
    async def scenario():
        store, manager, lease, jid, future = environment(tmp_path)
        a = {**answer(), 'value': 'Test folder'}
        acks, questions = [], []
        def handle(request):
            body = json.loads(request.content)
            if request.url.path.endswith('clara-ask'):
                questions.append(body)
                return wire(CONTRACT.document['fixtures']['clara-ask']['response'])
            if request.url.path.endswith('clara-commands'):
                return wire({'commands': [a], 'server_time': a['issued_at']})
            acks.append(body)
            if len(acks) == 1:
                raise httpx.ReadError('lost response', request=request)
            return wire({'command_id': 42, 'recorded': True, 'server_time': a['issued_at']})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            transport = PortalTransport(BASE, lambda: 'test-key', client=client)
            control = PortalControl(store, manager, transport, PortalJournal(store, BASE), lease, jid)
            await control.publish_questions()
            await control.publish_questions()
            assert len(questions) == 1
            assert questions[0]['question'] == 'Which folder?'
            assert questions[0]['explanation'] == 'Choose the destination.'
            assert questions[0]['details'] == 'Long optional details.'
            assert questions[0]['choices'] == ['Test folder']
            with pytest.raises(PortalUnavailable):
                await control.poll_commands()
            assert future.result() == 'Use the dedicated test folder only.'
            manager.pending.clear()
            control = PortalControl(store, manager, transport, PortalJournal(store, BASE), lease, jid)
            await control.poll_commands()
            assert acks[0] == acks[1]
            assert acks[1]['status'] == 'accepted'
    asyncio.run(scenario())


def test_unfinished_command_application_requires_recovery_instead_of_replay(tmp_path):
    async def scenario():
        store, manager, lease, jid, future = environment(tmp_path)
        a = answer()
        i = lease.identity
        store.execute("INSERT INTO portal_v1_commands VALUES(?,?,?,?,?,?,?,'processing',NULL)",
            (BASE, i.job_id, i.worker_id, i.attempt_no, i.fence_token, a['command_id'],
             json.dumps(a, sort_keys=True, separators=(',', ':'))))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: wire(
                {'commands': [a], 'server_time': a['issued_at']}))) as client:
            control = PortalControl(store, manager, PortalTransport(BASE, lambda: 'test-key', client=client),
                                    PortalJournal(store, BASE), lease, jid)
            with pytest.raises(PortalUnavailable, match='needs review'):
                await control.poll_commands()
            assert not future.done()
    asyncio.run(scenario())


def test_busy_heartbeat_without_a_lease_stops_local_work(tmp_path):
    async def scenario():
        store, manager, lease, jid, _ = environment(tmp_path)
        body = {**CONTRACT.document['fixtures']['clara-heartbeat']['response'], 'lease_expires_at': None}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: wire(body))) as client:
            control = PortalControl(store, manager, PortalTransport(BASE, lambda: 'test-key', client=client),
                                    PortalJournal(store, BASE), lease, jid)
            with pytest.raises(LeaseLost):
                await control.heartbeat()
            assert store.job(jid)['status'] == 'cancelled'
    asyncio.run(scenario())
