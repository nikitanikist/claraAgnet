import asyncio
from datetime import datetime, timezone, timedelta
import hashlib

import httpx
import pytest

from clara.config import Config
from clara.portal_artifacts import PortalUploads, published_snapshot
from clara.portal_contract import PortalContract
from clara.portal_lease import AttemptIdentity, ExecutionLease, LeaseLost
from clara.portal_transport import PortalTransport, PortalUnavailable
from clara.store import Store
from clara.tools import publish_artifact


BASE = 'https://example.supabase.co/functions/v1'
IDENTITY = AttemptIdentity('11111111-1111-4111-8111-111111111111',
                           '22222222-2222-4222-8222-222222222222', 3, 91)
NOW = datetime(2026, 9, 14, 13, tzinfo=timezone.utc)


@pytest.fixture
def published(tmp_path):
    config = Config(tmp_path / 'data')
    config.initialize()
    store = Store(config.data / 'db')
    conversation = store.create_conversation()
    job = store.create_job(conversation['id'], 'Prepare a PDF', 'autonomous', [])
    data = b'%PDF-1.4\nSynthetic file bytes for transport tests; not a verified tax document.'
    source = config.workspace / 'example.pdf'
    source.write_bytes(data)
    result = publish_artifact(config, store, job, source)
    fid = result['id']
    snapshot = published_snapshot(config, store, job['id'], fid, expected_sha256=hashlib.sha256(data).hexdigest())
    allocation = PortalContract.bundled().document['fixtures']['clara-artifact-upload-url']['response'].copy()
    allocation.update(original_file_name=snapshot.name, storage_path=f'{IDENTITY.job_id}/3/example.pdf',
                      upload_url=f'https://example.supabase.co/storage/v1/upload/sign/clara-artifacts/{IDENTITY.job_id}/3/example.pdf?token=synthetic',
                      expires_at=(NOW + timedelta(minutes=15)).isoformat(), server_time=NOW.isoformat())
    clock = [0.0]
    lease = ExecutionLease(IDENTITY, clock=lambda: clock[0])
    lease.acknowledge(IDENTITY, expires_at=NOW + timedelta(seconds=120), server_time=NOW, request_started=0)
    return config, store, job, snapshot, allocation, lease, clock


def test_published_file_is_scoped_and_checked_against_evidence(published):
    config, store, job, snapshot, _, _, _ = published
    other = store.create_conversation()
    other_job = store.create_job(other['id'], 'Other staff member', 'autonomous', [])
    with pytest.raises(ValueError, match='conversation'):
        published_snapshot(config, store, other_job['id'], snapshot.file_id, expected_sha256=snapshot.sha256)
    with pytest.raises(ValueError, match='evidence'):
        published_snapshot(config, store, job['id'], snapshot.file_id, expected_sha256='0' * 64)


def test_upload_sends_exact_bytes_without_worker_credentials_and_is_not_repeated(published):
    _, store, _, snapshot, allocation, lease, clock = published
    calls = []
    async def handler(request):
        calls.append(request)
        assert await request.aread() == snapshot.data
        assert request.headers['content-type'] == 'application/pdf'
        assert 'x-clara-worker-key' not in request.headers
        assert 'authorization' not in request.headers
        assert 'cookie' not in request.headers
        return httpx.Response(200, json={'Key': allocation['storage_path']})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     headers={'x-clara-worker-key': 'must-not-leak'},
                                     auth=('username', 'password'), cookies={'session': 'must-not-leak'}) as client:
            transport = PortalTransport(BASE, lambda: 'worker-secret', client=client)
            uploader = PortalUploads(store, transport, client=client, clock=lambda: clock[0])
            first = await uploader.upload(IDENTITY, lease, snapshot, allocation, allocation_request_started=0)
            assert first['state'] == 'uploaded'
            second = await uploader.upload(IDENTITY, lease, snapshot, allocation, allocation_request_started=0)
            assert second == first
            assert len(calls) == 1
    asyncio.run(scenario())


def test_lost_upload_receipt_survives_restart_and_does_not_trigger_another_put(published):
    _, store, _, snapshot, allocation, lease, clock = published
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadError('private URL or response body', request=request)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = PortalTransport(BASE, lambda: 'worker-secret', client=client)
            for db in (store, Store(store.path)):
                uploader = PortalUploads(db, transport, client=client, clock=lambda: clock[0])
                with pytest.raises(PortalUnavailable) as caught:
                    await uploader.upload(IDENTITY, lease, snapshot, allocation, allocation_request_started=0)
                assert 'private URL' not in str(caught.value)
            assert len(calls) == 1
            row = store.one('SELECT * FROM portal_v1_uploads')
            assert row['state'] == 'unknown'
            assert 'upload_url' not in row
    asyncio.run(scenario())


def test_upload_rejects_cross_portal_url_before_sending(published):
    _, store, _, snapshot, allocation, lease, clock = published
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('Must not send'))) as client:
            transport = PortalTransport(BASE, lambda: 'worker-secret', client=client)
            uploader = PortalUploads(store, transport, client=client, clock=lambda: clock[0])
            with pytest.raises(ValueError):
                await uploader.upload(IDENTITY, lease, snapshot,
                                      {**allocation, 'upload_url': allocation['upload_url'].replace('example.supabase.co', 'other.invalid')},
                                      allocation_request_started=0)
            assert store.rows('SELECT * FROM portal_v1_uploads') == []
    asyncio.run(scenario())


def test_upload_rejects_a_changed_original_filename_before_sending(published):
    _, store, _, snapshot, allocation, lease, clock = published
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('Must not upload a misnamed file'))) as client:
            uploader = PortalUploads(store, PortalTransport(BASE, lambda:'test', client=client), client=client, clock=lambda:clock[0])
            with pytest.raises(ValueError, match='original filename'):
                await uploader.upload(IDENTITY, lease, snapshot,
                    {**allocation, 'original_file_name':'different-client.pdf'}, allocation_request_started=0)
            assert store.rows('SELECT * FROM portal_v1_uploads') == []
    asyncio.run(scenario())


def test_expired_lease_cancels_a_stalled_transfer_and_keeps_unknown_outcome(published):
    _, store, _, snapshot, allocation, lease, clock = published
    cleaned = asyncio.Event()
    async def handler(request):
        clock[0] = 121
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = PortalTransport(BASE, lambda: 'worker-secret', client=client)
            uploader = PortalUploads(store, transport, client=client, clock=lambda: clock[0])
            with pytest.raises(LeaseLost):
                await asyncio.wait_for(uploader.upload(IDENTITY, lease, snapshot, allocation,
                                                       allocation_request_started=0), timeout=1)
            assert cleaned.is_set()
            assert store.one('SELECT state FROM portal_v1_uploads')['state'] == 'unknown'
    asyncio.run(scenario())
