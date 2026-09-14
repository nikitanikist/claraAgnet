"""Upload a bounded immutable snapshot of a published local attachment.

An upload receipt proves transport only. The portal must read the stored object
and verify its bytes before presenting it as a verified document.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
from pathlib import Path
import time
from urllib.parse import urlsplit, unquote

import httpx

from .portal_transport import PortalUnavailable, functions_base_url


MAX_BYTES = 50 * 1024 * 1024
MIMES = {
    '.pdf': 'application/pdf', '.png': 'image/png', '.csv': 'text/csv',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}


@dataclass(frozen=True)
class PublishedFile:
    file_id: str
    name: str
    data: bytes
    sha256: str
    content_type: str


def published_snapshot(config, store, local_job_id, file_id, *, expected_sha256):
    job = store.job(local_job_id)
    row = store.one('SELECT * FROM files WHERE id=? AND kind=?', (file_id, 'artifact'))
    if not job or not row or row['conversation_id'] != job['conversation_id']:
        raise ValueError('Choose a published attachment from this portal conversation.')
    path = Path(row['path']).resolve()
    if not path.is_relative_to((config.data / 'artifacts').resolve()) or not path.is_file():
        raise ValueError('The published attachment is unavailable.')
    content_type = MIMES.get(Path(row['name']).suffix.lower())
    if content_type is None or row['size'] > MAX_BYTES:
        raise ValueError('This attachment type or size is not supported by the portal.')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES or len(data) != row['size']:
        raise ValueError('The published attachment changed or exceeds the upload limit.')
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError('The attachment no longer matches its verified evidence.')
    if content_type == 'application/pdf' and not data.startswith(b'%PDF-'):
        raise ValueError('This attachment is not a PDF.')
    if content_type == 'image/png' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('This attachment is not a PNG.')
    return PublishedFile(row['id'], row['name'], data, digest, content_type)


class PortalUploads:
    def __init__(self, store, transport, *, client=None, clock=time.monotonic):
        self.store, self.transport = store, transport
        self.namespace = functions_base_url(transport.base_url)
        self.clock = clock
        self._owns_client = client is None
        # A separate client prevents worker-auth defaults from reaching storage.
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False)

    async def close(self):
        if self._owns_client:
            await self.client.aclose()

    def _allocation_url(self, identity, allocation):
        self.transport.contract.validate('clara-artifact-upload-url', 'response', allocation)
        base = urlsplit(self.namespace)
        url = urlsplit(allocation['upload_url'])
        path = allocation['storage_path']
        if (not path.startswith(f'{identity.job_id}/{identity.attempt_no}/')
                or any(p in ('', '.', '..') for p in path.split('/')) or '\\' in path or '%' in path):
            raise ValueError('The upload allocation belongs to a different attempt or path.')
        try:
            valid = (url.scheme == 'https' and url.hostname == base.hostname and url.port in (None, 443)
                     and not url.username and not url.password and not url.fragment
                     and unquote(url.path) == '/storage/v1/upload/sign/clara-artifacts/' + path)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('The upload URL does not match this portal allocation.')
        return allocation['upload_url']

    async def upload(self, identity, lease, file, allocation, *, allocation_request_started):
        if lease.identity != identity:
            raise ValueError('The upload lease belongs to a different attempt.')
        lease.assert_active()
        url = self._allocation_url(identity, allocation)
        expires = datetime.fromisoformat(allocation['expires_at'].replace('Z', '+00:00'))
        server = datetime.fromisoformat(allocation['server_time'].replace('Z', '+00:00'))
        if (type(allocation_request_started) not in (int, float)
                or not math.isfinite(allocation_request_started)):
            raise ValueError('The upload allocation has invalid timing.')
        deadline = allocation_request_started + (expires - server).total_seconds() - 5
        if deadline <= self.clock() or allocation_request_started > self.clock():
            raise ValueError('The upload allocation has expired.')
        if (not isinstance(file, PublishedFile) or not file.data or len(file.data) > MAX_BYTES
                or hashlib.sha256(file.data).hexdigest() != file.sha256):
            raise ValueError('Provide the verified immutable attachment snapshot.')
        if allocation['original_file_name'] != file.name:
            raise ValueError('The allocation does not preserve this attachment\'s original filename.')
        args = (self.namespace, identity.job_id, identity.attempt_no, identity.fence_token, file.file_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('''SELECT * FROM portal_v1_uploads WHERE namespace=? AND external_job_id=?
                AND attempt_no=? AND fence_token=? AND file_id=?''', args).fetchone()
            if old:
                if (old['worker_id'] != identity.worker_id or old['sha256'] != file.sha256
                        or old['storage_path'] != allocation['storage_path']
                        or old['allocation_id'] != allocation['allocation_id']):
                    raise ValueError('This attachment already has a different allocation.')
                if old['state'] == 'uploaded':
                    return dict(old)
                raise PortalUnavailable('This upload has an uncertain outcome; verify its stored object before retrying.')
            db.execute('''INSERT INTO portal_v1_uploads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (self.namespace, identity.job_id, identity.worker_id, identity.attempt_no,
                        identity.fence_token, file.file_id, allocation['allocation_id'],
                        allocation['storage_path'], file.sha256, len(file.data), file.content_type,
                        'uploading', time.time()))

        async def chunks():
            for offset in range(0, len(file.data), 65536):
                lease.assert_active()
                if self.clock() >= deadline:
                    raise PortalUnavailable('The upload allocation expired during transfer.')
                yield file.data[offset:offset + 65536]

        state = 'unknown'
        async def transfer():
            nonlocal state
            # Construct a standalone request: even an injected client's default
            # auth headers/cookies must not be applied to this signed URL.
            request = httpx.Request('PUT', url, content=chunks(),
                                    headers={'content-type': file.content_type,
                                             'content-length': str(len(file.data))})
            response = await self.client.send(request, stream=True, follow_redirects=False, auth=None)
            try:
                if not 200 <= response.status_code < 300:
                    raise PortalUnavailable('Storage did not acknowledge the upload; verify the existing object.')
                state = 'uploaded'
            finally:
                await response.aclose()

        task = asyncio.create_task(transfer())
        monitor = asyncio.create_task(lease.wait_until_lost())
        try:
            done, _ = await asyncio.wait((task, monitor), return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                raise monitor.result()
            await task
            lease.assert_active()
        except (httpx.HTTPError, OSError):
            raise PortalUnavailable('The upload receipt was lost; verify the existing object before retrying.') from None
        finally:
            task.cancel()
            monitor.cancel()
            await asyncio.gather(task, monitor, return_exceptions=True)
            self.store.execute('''UPDATE portal_v1_uploads SET state=?,updated=?
                WHERE namespace=? AND external_job_id=? AND attempt_no=? AND fence_token=? AND file_id=?''',
                               (state, time.time(), *args))
        return self.store.one('''SELECT * FROM portal_v1_uploads WHERE namespace=? AND external_job_id=?
            AND attempt_no=? AND fence_token=? AND file_id=?''', args)
