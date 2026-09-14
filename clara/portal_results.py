"""Deliver one completed attempt's artifacts and immutable result report."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .knowledge import decode
from .portal_artifacts import PortalUploads, published_snapshot
from .portal_documents import collect_documents
from .portal_progress import check_binding
from .portal_transport import PortalUnavailable
from .portal_usage import portal_usage
from .workflows import Workflows


class PortalResults:
    def __init__(self, config, store, transport, journal, *, uploads=None):
        self.config, self.store, self.transport, self.journal = config, store, transport, journal
        self.uploads = uploads or PortalUploads(store, transport)
        self.owns_uploads = uploads is None

    async def close(self):
        if self.owns_uploads:
            await self.uploads.close()

    async def _file(self, lease, file, fields):
        lease.assert_active()
        identity = lease.identity
        previous = self.store.one('''SELECT * FROM portal_v1_uploads WHERE namespace=? AND external_job_id=?
            AND attempt_no=? AND fence_token=? AND file_id=?''',
            (self.transport.base_url, identity.job_id, identity.attempt_no, identity.fence_token, file.file_id))
        if previous:
            if (previous['worker_id'] != identity.worker_id or previous['state'] != 'uploaded'
                    or previous['sha256'] != file.sha256 or previous['bytes'] != len(file.data)):
                raise PortalUnavailable('An earlier upload needs reconciliation before another transfer.')
            path = previous['storage_path']
        else:
            allocation = await self.transport.request('clara-artifact-upload-url', {**asdict(identity), **fields})
            uploaded = await self.uploads.upload(identity, lease, file, allocation.body,
                                                 allocation_request_started=allocation.request_started)
            path = uploaded['storage_path']
        return {'kind': 'screenshot' if file.content_type == 'image/png' else 'document',
                'member_id': fields.get('member_id'), 'document_type': fields.get('document_type'),
                'tax_year': fields.get('tax_year'), 'storage_path': path, 'sha256': file.sha256,
                'bytes': len(file.data), 'content_type': file.content_type, 'verification': 'declared'}

    def _closeout(self, job, identity, claim):
        wf = Workflows(self.store, self.config)
        state = wf.snapshot(job['conversation_id'])
        if not state or any(v['status'] != 'verified' for k, v in state['stages'].items() if k != 'review'):
            raise ValueError('Some closeout stages are still unfinished. Review the saved checkpoints.')
        for stage in state['stages'].values():
            wf._proofs(job, stage['evidence_ids'])
        row = self.store.one("SELECT * FROM evidence WHERE job_id=? AND kind='portal_delivery' AND verified=1 ORDER BY created DESC LIMIT 1", (job['id'],))
        if not row:
            raise ValueError('Record the verified member-specific delivery outputs before handing off this closeout.')
        delivery = decode(row, 'payload')['payload']
        if (delivery['attempt_no'], delivery['fence_token']) != (identity.attempt_no, identity.fence_token):
            raise ValueError('The delivery evidence belongs to another portal attempt.')
        documents = collect_documents(self.config, self.store, self.transport.base_url,
                                      identity, job['id'], delivery['document_evidence_ids'])
        return documents, delivery['artifacts']

    async def deliver(self, prepared, timing):
        identity, lease, jid = prepared.lease.identity, prepared.lease, prepared.local_job_id
        binding = check_binding(self.store, self.transport.base_url, identity, jid)
        key = 'result-' + jid
        # Once staged, a retry always reuses the exact original result. It does
        # not re-upload files, recompute usage or reinterpret a model reply.
        previous = self.store.one('''SELECT payload FROM portal_v1_outbox WHERE namespace=?
            AND external_job_id=? AND worker_id=? AND attempt_no=? AND fence_token=?
            AND operation='clara-result' AND request_key=?''',
            (self.transport.base_url, identity.job_id, identity.worker_id, identity.attempt_no, identity.fence_token, key))
        if previous:
            return await self.transport.report(self.journal, identity, 'clara-result', key, json.loads(previous['payload']))
        lease.assert_active()
        job = self.store.job(jid)
        if job['status'] in {'queued', 'running', 'waiting', 'cancelling'}:
            raise ValueError('Wait for the local task and its tool calls to finish before delivering results.')
        claim = json.loads(binding['claim_json'])
        last = self.store.one("SELECT data FROM events WHERE job_id=? AND kind='assistant' ORDER BY id DESC LIMIT 1", (jid,))
        text = json.loads(last['data']).get('text', '') if last else ''
        # Full text is delivered by the progress channel; the result is a short
        # summary and never the only stored copy of a longer answer.
        summary = text[:2000] or 'Local execution ended. Review the saved progress and outputs.'
        outcome = 'failed' if job['status'] == 'failed' else 'needs_review'
        reason = 'Execution stopped before all preparation steps were confirmed.'
        artifacts = []
        if not prepared.recovered and job['status'] in {'completed', 'needs_review'}:
            if claim['kind'] == 'closeout':
                try:
                    documents, remotes = self._closeout(job, identity, claim)
                except ValueError as error:
                    reason = str(error)[:600]
                else:
                    for document in documents:
                        artifacts.append(await self._file(lease, document.file, document.allocation_fields()))
                    artifacts.extend(remotes)
                    outcome, reason = 'completed_prepared', None
            else:
                # Every file belongs to this task, not merely to a shared folder.
                for row in self.store.rows("SELECT * FROM files WHERE job_id=? AND kind='artifact' ORDER BY created", (jid,)):
                    path = Path(row['path']).resolve()
                    if not path.is_relative_to((self.config.data / 'artifacts').resolve()) or not path.is_file():
                        raise ValueError('A published task attachment is unavailable.')
                    if path.stat().st_size > 50 * 1024 * 1024:
                        raise ValueError('A published task attachment exceeds the portal upload limit.')
                    file = published_snapshot(self.config, self.store, jid, row['id'],
                                               expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                    artifacts.append(await self._file(lease, file, {
                        'file_name': file.name, 'content_type': file.content_type,
                        'bytes': len(file.data), 'sha256': file.sha256}))
                if job['status'] == 'completed':
                    outcome, reason = 'completed_prepared', None
        payload = {**asdict(identity), 'idempotency_key': key, 'outcome': outcome,
                   'needs_review_reason': reason, 'summary': summary, 'artifacts': artifacts,
                   'usage': portal_usage(job['usage'], **timing)}
        return await self.transport.report(self.journal, identity, 'clara-result', key, payload)
