import asyncio
import copy
from dataclasses import fields

import httpx
import pytest

from clara.portal_contract import ContractViolation, PortalContract
from clara.portal_journal import JournalConflict, PortalJournal
from clara.portal_lease import AttemptIdentity
from clara.portal_transport import PortalRejected, PortalTransport, PortalUnavailable
from clara.store import Store


BASE = 'https://example.supabase.co/functions/v1'
KEY = 'synthetic-worker-secret'
CONTRACT = PortalContract.bundled()


def fixture(name, direction='request'):
    return copy.deepcopy(CONTRACT.document['fixtures'][name][direction])


def wire(body, status=200, **headers):
    return httpx.Response(status, json=body, headers={'x-clara-contract': '1', **headers})


def test_bundled_portal_fixtures_and_discriminated_claims():
    for name, values in CONTRACT.document['fixtures'].items():
        for direction in ('request', 'response'):
            CONTRACT.validate(name, direction, values[direction])
    with pytest.raises(ContractViolation):
        CONTRACT.validate('clara-claim', 'response', {'claimed': True, 'server_time': '2026-09-14T13:00:00Z'})
    with pytest.raises(ContractViolation):
        CONTRACT.validate('clara-heartbeat', 'request', {'worker_id': fixture('clara-heartbeat')['worker_id'], 'busy': True})


def test_only_valid_worker_requests_leave_the_machine():
    calls = []
    def handler(request):
        calls.append(request)
        return wire(fixture('clara-heartbeat', 'response'))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = PortalTransport(BASE, lambda: KEY, client=client, clock=lambda: 12.5)
            with pytest.raises(ContractViolation):
                await transport.request('clara-assign', fixture('clara-assign'))
            with pytest.raises(ContractViolation):
                await transport.request('clara-heartbeat', {'worker_id': 'bad'})
            assert calls == []
            reply = await transport.request('clara-heartbeat', fixture('clara-heartbeat'))
            assert reply.request_started == 12.5
            assert calls[0].url == BASE + '/clara-heartbeat'
            assert calls[0].headers['x-clara-worker-key'] == KEY
            assert calls[0].headers['x-clara-contract'] == '1'
            assert 'authorization' not in calls[0].headers
    asyncio.run(scenario())


@pytest.mark.parametrize('response', [
    httpx.Response(307, headers={'location': 'https://other.invalid/collect', 'x-clara-contract': '1', 'content-type': 'application/json'}, json={}),
    httpx.Response(200, json=fixture('clara-heartbeat', 'response')),
    httpx.Response(200, text='<html>private-response</html>', headers={'x-clara-contract': '1'}),
    wire({'unexpected': 'private-response'}),
    wire({'error': 'invented-private-response', 'message': 'private-response', 'retryable': True}, 500),
    httpx.Response(200, content=b' ' * 1_048_577, headers={'x-clara-contract': '1', 'content-type': 'application/json'}),
])
def test_incompatible_responses_and_redirects_do_not_pass_or_leak(response):
    calls = []
    def handler(request):
        calls.append(request)
        return response
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            transport = PortalTransport(BASE, lambda: KEY, client=client)
            with pytest.raises((ContractViolation, PortalUnavailable)) as caught:
                await transport.request('clara-heartbeat', fixture('clara-heartbeat'))
            assert 'private-response' not in str(caught.value)
            assert KEY not in str(caught.value)
            assert len(calls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('code', ['lease_expired', 'finalization_in_progress'])
def test_lease_rejection_is_explicit_without_server_message(code):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: wire(
                {'error': code, 'message': 'private-client-content', 'retryable': False}, 409))) as client:
            transport = PortalTransport(BASE, lambda: KEY, client=client)
            with pytest.raises(PortalRejected) as caught:
                await transport.request('clara-heartbeat', fixture('clara-heartbeat'))
            assert caught.value.code == code
            assert 'private-client-content' not in str(caught.value)
    asyncio.run(scenario())


@pytest.mark.parametrize('handoff_status', ['ready_to_email', 'not_applicable'])
def test_lost_result_response_retries_original_report_after_restart(tmp_path, handoff_status):
    path = tmp_path / 'db'
    body = fixture('clara-result')
    identity = AttemptIdentity(**{f.name: body[f.name] for f in fields(AttemptIdentity)})
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadError('sensitive response details', request=request)
        response = fixture('clara-result', 'response')
        if handoff_status == 'not_applicable':
            response['handoff'] = {'attempted': False, 'status': 'not_applicable', 'reason': None}
        return wire(response)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = PortalTransport(BASE, lambda: KEY, client=client)
            journal = PortalJournal(Store(path), BASE)
            with pytest.raises(PortalUnavailable):
                await transport.report(journal, identity, 'clara-result', body['idempotency_key'], body)
            assert len(journal.pending()) == 1
            reopened = Store(path)
            reopened.recover()
            journal = PortalJournal(reopened, BASE)
            receipt = await transport.report(journal, identity, 'clara-result', body['idempotency_key'], body)
            assert receipt['result_recorded'] is True
            assert calls[0].content == calls[1].content
            assert calls[0].headers['idempotency-key'] == calls[1].headers['idempotency-key']
            assert journal.pending() == []
            assert reopened.rows('SELECT * FROM jobs') == []
            assert await transport.report(journal, identity, 'clara-result', body['idempotency_key'], body) == receipt
            assert len(calls) == 2
            with pytest.raises(JournalConflict):
                await transport.report(journal, identity, 'clara-result', body['idempotency_key'], {**body, 'summary': 'different'})
    asyncio.run(scenario())


def test_wrong_command_receipt_cannot_acknowledge_local_outbox(tmp_path):
    body = fixture('clara-command-ack')
    identity = AttemptIdentity(**{f.name: body[f.name] for f in fields(AttemptIdentity)})
    response = {**fixture('clara-command-ack', 'response'), 'command_id': body['command_id'] + 1}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: wire(response))) as client:
            transport = PortalTransport(BASE, lambda: KEY, client=client)
            journal = PortalJournal(Store(tmp_path / 'db'), BASE)
            with pytest.raises(PortalUnavailable):
                await transport.report(journal, identity, 'clara-command-ack', 'ack-42', body)
            assert len(journal.pending()) == 1
    asyncio.run(scenario())
