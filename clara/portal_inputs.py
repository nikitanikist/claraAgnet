"""Download the assigned source files before acknowledging task delivery.

The portal authorizes each attachment by its ID and exact attempt. Signed URLs
are used by a separate, credential-free client and are never saved in history.
Receiving a file does not execute it or treat its contents as instructions.
"""
import asyncio
from dataclasses import asdict
from datetime import datetime
import hashlib
import os
from pathlib import Path, PureWindowsPath
import time
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import httpx

from .portal_contract import ContractViolation
from .portal_transport import PortalUnavailable


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TASK_BYTES = 250 * 1024 * 1024


class PortalInputs:
    def __init__(self, config, store, transport, *, client=None):
        self.config, self.store, self.transport = config, store, transport
        self.namespace = transport.base_url
        self.owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False)

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    def _url(self, reply, attachment):
        data = reply.body
        if data['attachment_id'] != attachment['attachment_id'] or data['name'] != attachment['name']:
            raise ContractViolation('The portal returned a different source attachment.')
        u, origin = urlsplit(data['download_url']), urlsplit(self.namespace)
        decoded = unquote(u.path)
        try:
            valid = (u.scheme == 'https' and u.hostname == origin.hostname and u.port in (None, 443)
                     and not u.username and not u.password and not u.fragment
                     and decoded.startswith('/storage/v1/object/sign/')
                     and len(decoded.split('/')) >= 7
                     and not any(p in {'.', '..', ''} for p in decoded.split('/')[1:])
                     and '\\' not in decoded)
        except ValueError:
            valid = False
        if not valid:
            raise ContractViolation('The source attachment URL does not belong to this portal storage.')
        expires = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        server = datetime.fromisoformat(data['server_time'].replace('Z', '+00:00'))
        deadline = reply.request_started + (expires - server).total_seconds() - 5
        if reply.request_started > self.transport.clock() or deadline <= self.transport.clock():
            raise PortalUnavailable('The source attachment URL expired. Request a fresh download.')
        return data['download_url'], deadline

    async def receive(self, claim, lease):
        self.transport.contract.validate('clara-claim', 'response', claim)
        identity = lease.identity
        if (claim.get('claimed') is not True or claim['job_id'] != identity.job_id
                or claim['attempt_no'] != identity.attempt_no or claim['fence_token'] != identity.fence_token):
            raise ContractViolation('The source files belong to another portal attempt.')
        attachments = (claim.get('closeout') or {}).get('attachments', [])
        if len({a['attachment_id'] for a in attachments}) != len(attachments):
            raise ContractViolation('The assignment repeats a source attachment ID.')
        received, total = [], 0
        for attachment in attachments:
            lease.assert_active()
            item = await self._one(attachment, lease, remaining=MAX_TASK_BYTES - total)
            total += item['bytes']
            received.append(item)
        return received

    async def _one(self, attachment, lease, *, remaining):
        identity = lease.identity
        args = (self.namespace, identity.job_id, identity.worker_id, identity.attempt_no,
                identity.fence_token, attachment['attachment_id'])
        old = self.store.one('''SELECT * FROM portal_v1_inputs WHERE namespace=? AND external_job_id=?
            AND worker_id=? AND attempt_no=? AND fence_token=? AND attachment_id=?''', args)
        root = (self.config.data / 'attachments').resolve()
        if old:
            path = Path(old['path']).resolve()
            if (old['name'] != attachment['name'] or not path.is_relative_to(root)
                    or not path.is_file() or not 0 <= old['bytes'] <= min(MAX_FILE_BYTES, remaining)):
                raise ContractViolation('The saved source file no longer matches this assignment.')
            if path.stat().st_size != old['bytes']:
                raise ContractViolation('A saved source attachment changed; review the existing task before resuming.')
            with path.open('rb') as saved_file:
                # Also bound the read if another process changes the file after
                # the stat check. Never load an arbitrarily grown file.
                data = saved_file.read(old['bytes'] + 1)
            if len(data) != old['bytes'] or hashlib.sha256(data).hexdigest() != old['sha256']:
                raise ContractViolation('A saved source attachment changed; review the existing task before resuming.')
            return {k: old[k] for k in ('attachment_id', 'name', 'path', 'bytes', 'sha256')}

        reply = await self.transport.request('clara-attachment', {**asdict(identity),
                                               'attachment_id': attachment['attachment_id']})
        lease.assert_active()
        url, deadline = self._url(reply, attachment)
        directory = root / 'portal' / hashlib.sha256(self.namespace.encode()).hexdigest()[:20] / identity.job_id / str(identity.attempt_no)
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.resolve().is_relative_to(root):
            raise ContractViolation('The source attachment directory was redirected outside Clara storage.')
        # Original display name is metadata; it is never a filesystem path.
        suffix = PureWindowsPath(attachment['name']).suffix
        suffix = suffix if len(suffix) <= 12 and suffix[1:].isalnum() else '.bin'
        path = directory / (attachment['attachment_id'] + '-' + uuid4().hex + suffix)
        digest, count = hashlib.sha256(), 0

        async def download():
            nonlocal count
            request = httpx.Request('GET', url)
            response = await self.client.send(request, stream=True, follow_redirects=False, auth=None)
            try:
                if response.status_code != 200:
                    raise PortalUnavailable('The portal source file could not be downloaded.')
                with path.open('xb') as output:
                    async for chunk in response.aiter_bytes():
                        lease.assert_active()
                        if self.transport.clock() >= deadline:
                            raise PortalUnavailable('The source attachment URL expired during transfer.')
                        count += len(chunk)
                        if count > min(MAX_FILE_BYTES, remaining):
                            raise PortalUnavailable('The source files exceed the task download limit.')
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                await response.aclose()

        task, monitor = asyncio.create_task(download()), asyncio.create_task(lease.wait_until_lost())
        saved = False
        try:
            done, _ = await asyncio.wait((task, monitor), return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                raise monitor.result()
            await task
            lease.assert_active()
            self.store.execute('INSERT INTO portal_v1_inputs VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                               (*args, attachment['name'], str(path), count, digest.hexdigest(), time.time()))
            saved = True
        except (httpx.HTTPError, OSError):
            raise PortalUnavailable('The source download did not finish; the task has not started.') from None
        finally:
            task.cancel()
            monitor.cancel()
            await asyncio.gather(task, monitor, return_exceptions=True)
            if not saved:
                path.unlink(missing_ok=True)
        return {'attachment_id': attachment['attachment_id'], 'name': attachment['name'],
                'path': str(path), 'bytes': count, 'sha256': digest.hexdigest()}
