import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import httpx
import pytest

from clara.portal_contract import ContractViolation
from clara.portal_inputs import PortalInputs
from clara.portal_lease import LeaseLost
from clara.portal_transport import PortalTransport, PortalUnavailable
from test_portal_delivery import BASE, CONTRACT, setup, wire


def attach(claim):
    claim['closeout']['attachments'] = [{'attachment_id': '88888888-8888-4888-8888-888888888888',
                                         'name': 'Tax slips.pdf'}]
    return claim['closeout']['attachments'][0]


def ticket(attachment, **changes):
    return {'attachment_id': attachment['attachment_id'], 'name': attachment['name'],
            'download_url': 'https://example.supabase.co/storage/v1/object/sign/documents/slips.pdf?token=temporary',
            'expires_at': '2026-09-14T00:05:00Z', 'server_time': '2026-09-14T00:00:00Z', **changes}


def test_inputs_download_exact_assignment_without_credentials_and_reuse_verified_bytes(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    attachment = attach(claim)
    data = b'%PDF-1.7\nsource slips'
    calls = []
    async def scenario():
        def auth(request):
            calls.append('ticket')
            assert json.loads(request.content) == {**asdict(lease.identity), 'attachment_id': attachment['attachment_id']}
            return wire(ticket(attachment))
        def storage(request):
            calls.append('storage')
            assert 'authorization' not in request.headers and 'x-clara-worker-key' not in request.headers
            assert 'cookie' not in request.headers
            return httpx.Response(200, content=data)
        async with httpx.AsyncClient(transport=httpx.MockTransport(auth)) as api, \
                httpx.AsyncClient(transport=httpx.MockTransport(storage), headers={'authorization': 'must-not-leak'},
                                  cookies={'private': 'must-not-leak'}) as blobs:
            inputs = PortalInputs(config, store, PortalTransport(BASE, lambda: 'worker-private', client=api, clock=lambda: 100), client=blobs)
            files = await inputs.receive(claim, lease)
            assert files[0]['name'] == 'Tax slips.pdf'
            path = Path(files[0]['path'])
            assert path.is_relative_to(config.data / 'attachments')
            assert path.read_bytes() == data and files[0]['sha256'] == hashlib.sha256(data).hexdigest()
            assert await inputs.receive(claim, lease) == files
            assert calls == ['ticket', 'storage']
            assert 'temporary' not in json.dumps(store.rows('SELECT * FROM portal_v1_inputs'))
            path.write_bytes(b'changed')
            with pytest.raises(ContractViolation, match='changed'):
                await inputs.receive(claim, lease)
            assert calls == ['ticket', 'storage']
    asyncio.run(scenario())


@pytest.mark.parametrize('changes', [
    {'attachment_id': '99999999-9999-4999-8999-999999999999'},
    {'name': 'different.pdf'},
    {'download_url': 'https://other.example/storage/v1/object/sign/documents/slips.pdf'},
    {'download_url': 'https://example.supabase.co/storage/v1/object/sign/documents/%2e%2e/private'},
])
def test_mismatched_or_redirected_attachment_is_refused_before_storage(tmp_path, changes):
    config, store, claim, lease = setup(tmp_path)
    attachment = attach(claim)
    async def scenario():
        def storage(request):
            pytest.fail('A mismatched attachment must not reach storage.')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: wire(ticket(attachment, **changes)))) as api, \
                httpx.AsyncClient(transport=httpx.MockTransport(storage)) as blobs:
            inputs = PortalInputs(config, store, PortalTransport(BASE, lambda: 'test', client=api, clock=lambda: 100), client=blobs)
            with pytest.raises(ContractViolation):
                await inputs.receive(claim, lease)
            assert store.rows('SELECT * FROM portal_v1_inputs') == []
    asyncio.run(scenario())


def test_lost_lease_interrupts_hung_download_and_never_registers_partial_input(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    attachment = attach(claim)
    async def scenario():
        cancelled = asyncio.Event()
        async def storage(request):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        lease.clock = time.monotonic
        lease.deadline = time.monotonic() + .05
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: wire(ticket(attachment)))) as api, \
                httpx.AsyncClient(transport=httpx.MockTransport(storage)) as blobs:
            inputs = PortalInputs(config, store, PortalTransport(BASE, lambda: 'test', client=api), client=blobs)
            with pytest.raises(LeaseLost):
                await asyncio.wait_for(inputs.receive(claim, lease), 1)
            assert cancelled.is_set()
            assert store.rows('SELECT * FROM portal_v1_inputs') == []
            assert not list((config.data / 'attachments').rglob('*.pdf'))
    asyncio.run(scenario())
