import asyncio
import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from clara.portal_artifacts import PortalUploads
from clara.portal_bindings import PortalBindings
from clara.portal_intake import PreparedAttempt
from clara.portal_journal import PortalJournal
from clara.portal_outputs import record_delivery
from clara.portal_results import PortalResults
from clara.portal_transport import PortalTransport, PortalUnavailable
from clara.store import Store
from clara.tools import publish_artifact
from clara.workflows import Workflows
from test_portal_delivery import BASE, WORKER, CONTRACT, setup, wire
from test_portal_outputs import delivery


TIMING = {'wall_seconds': 30, 'waiting_seconds': 4}


def test_lost_result_receipt_retries_original_report_after_restart_without_new_work(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    claim.update(kind='general', closeout=None, required_outputs=[])
    claim['scope']['closeout_form_id'] = None
    row = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Find the requested information.')
    jid = row['local_job_id']
    store.status(jid, 'completed')
    requests = []
    async def scenario():
        def handle(request):
            assert request.url.path.endswith('/clara-result')
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                raise httpx.ReadError('Lost receipt', request=request)
            return wire(CONTRACT.document['fixtures']['clara-result']['response'])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as api:
            transport = PortalTransport(BASE, lambda: 'test', client=api, clock=lambda: 100)
            reporter = PortalResults(config, store, transport, PortalJournal(store, BASE))
            try:
                with pytest.raises(PortalUnavailable):
                    await reporter.deliver(PreparedAttempt(jid, lease, False), TIMING)
                reopened = Store(store.path)
                reopened.recover()
                again = PortalResults(config, reopened, transport, PortalJournal(reopened, BASE))
                try:
                    result = await again.deliver(PreparedAttempt(jid, lease, True),
                                                  {'wall_seconds':99,'waiting_seconds':10})
                    assert result['result_recorded'] is True
                finally:
                    await again.close()
                assert requests[0] == requests[1]
                assert requests[0]['outcome'] == 'completed_prepared'
                assert requests[0]['usage']['active_seconds'] == 26
                assert requests[0]['usage']['estimated_cost_usd'] is None
                assert len(reopened.rows('SELECT id FROM jobs')) == 1
            finally:
                await reporter.close()
    asyncio.run(scenario())


def completed_delivery(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    proof = record_delivery(config, store, job, args)
    wf = Workflows(store, config)
    source = config.workspace / 'client-copy.pdf'
    source_proof = wf.evidence(job, 'source-copy', 'working copy',
                               {'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}, True)
    app = wf.evidence(job, 'desktop_assertion', 'Synthetic TaxPrep observation', {}, True)
    for stage, ids in [('intake',[]), ('source-copy',[source_proof['id']]), ('application',[app['id']]),
                       ('documents',args['document_evidence_ids']), ('signature-packet',proof['signature_evidence_ids']),
                       ('delivery',[proof['storage_evidence_id']])]:
        wf.checkpoint(job, stage, ids)
    store.status(job['id'], 'needs_review')
    return config, store, job, lease, args


def test_complete_closeout_hands_off_links_without_any_portal_pdf_upload(tmp_path):
    config, store, job, lease, args = completed_delivery(tmp_path)
    uploaded, result_bodies = [], []
    async def scenario():
        def handle(request):
            body = json.loads(request.content)
            assert request.url.path.endswith('/clara-result')
            result_bodies.append(body)
            return wire(CONTRACT.document['fixtures']['clara-result']['response'])
        async def storage(request):
            assert 'x-clara-worker-key' not in request.headers
            uploaded.append(await request.aread())
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as api, \
                httpx.AsyncClient(transport=httpx.MockTransport(storage)) as blobs:
            transport = PortalTransport(BASE, lambda:'test', client=api, clock=lambda:100)
            uploads = PortalUploads(store, transport, client=blobs, clock=lambda:100)
            reporter = PortalResults(config, store, transport, PortalJournal(store, BASE), uploads=uploads)
            prepared = PreparedAttempt(job['id'], lease, False)
            result = await reporter.deliver(prepared, TIMING)
            assert result['handoff']['status'] == 'ready_to_email'
            assert uploaded == []
            body = result_bodies[0]
            assert body['outcome'] == 'completed_prepared'
            assert [a['kind'] for a in body['artifacts']] == ['pandadoc','onedrive_folder']
            assert all('storage_path' not in a for a in body['artifacts'])
            files = body['artifacts'][-1]['evidence']['uploaded']
            assert len(files) == 3
            assert all(f['member_id']=='m1' and f['tax_year']=='2024' for f in files)
            await reporter.deliver(prepared, {'wall_seconds':100,'waiting_seconds':0})
            assert uploaded == [] and len(result_bodies) == 1
    asyncio.run(scenario())


def test_unfinished_closeout_reports_review_without_requesting_handoff(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    store.status(job['id'], 'incomplete', message='Workflow incomplete. Remaining stages: documents. Progress has been saved.')
    bodies = []
    async def scenario():
        def handle(request):
            assert request.url.path.endswith('/clara-result')
            bodies.append(json.loads(request.content))
            return wire(CONTRACT.document['fixtures']['clara-result']['response'])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as api:
            transport = PortalTransport(BASE, lambda:'test', client=api, clock=lambda:100)
            reporter = PortalResults(config, store, transport, PortalJournal(store, BASE))
            try:
                await reporter.deliver(PreparedAttempt(job['id'], lease, False), TIMING)
            finally:
                await reporter.close()
        assert bodies[0]['outcome'] == 'needs_review'
        assert bodies[0]['artifacts'] == []
        assert bodies[0]['needs_review_reason'] == 'Workflow incomplete. Remaining stages: documents. Progress has been saved.'
    asyncio.run(scenario())


def test_explicit_general_chat_file_request_still_uploads_the_requested_file(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    claim.update(kind='general', closeout=None, required_outputs=[])
    claim['scope']['closeout_form_id'] = None
    binding = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Find example.pdf and attach it here.')
    job = store.job(binding['local_job_id'])
    source = config.workspace / 'example.pdf'
    source.write_bytes(b'%PDF-1.4\nRequested file transport fixture.')
    publish_artifact(config, store, job, source)
    store.status(job['id'], 'completed')
    uploaded, reports = [], []
    async def scenario():
        def handle(request):
            body = json.loads(request.content)
            if request.url.path.endswith('/clara-artifact-upload-url'):
                path = f'{lease.identity.job_id}/{lease.identity.attempt_no}/{uuid4()}-example.pdf'
                return wire({'allocation_id':str(uuid4()), 'storage_path':path,
                    'original_file_name':'example.pdf',
                    'upload_url':'https://example.supabase.co/storage/v1/object/upload/sign/clara-artifacts/'+path+'?token=temporary',
                    'expires_at':'2026-09-14T00:05:00Z','server_time':'2026-09-14T00:00:00Z'})
            assert request.url.path.endswith('/clara-result')
            reports.append(body)
            return wire(CONTRACT.document['fixtures']['clara-result']['response'])
        async def storage(request):
            assert 'x-clara-worker-key' not in request.headers
            uploaded.append(await request.aread())
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as api, \
                httpx.AsyncClient(transport=httpx.MockTransport(storage)) as blobs:
            transport = PortalTransport(BASE, lambda:'test', client=api, clock=lambda:100)
            uploads = PortalUploads(store, transport, client=blobs, clock=lambda:100)
            reporter = PortalResults(config, store, transport, PortalJournal(store, BASE), uploads=uploads)
            await reporter.deliver(PreparedAttempt(job['id'], lease, False), TIMING)
            assert uploaded == [source.read_bytes()]
            assert reports[0]['artifacts'][0]['storage_path'].endswith('-example.pdf')
    asyncio.run(scenario())


def continued_attempt(tmp_path):
    """The first attempt recorded delivery; Review and continue starts a new attempt and fence."""
    from datetime import datetime, timedelta, timezone
    from clara.portal_bindings import PortalBindings
    from clara.portal_lease import AttemptIdentity, ExecutionLease
    config, store, job, lease, args = completed_delivery(tmp_path)
    import copy
    claim = copy.deepcopy(CONTRACT.document['fixtures']['clara-claim']['response'])
    claim['closeout']['attachments'] = []
    store.status(job['id'], 'incomplete')  # the first attempt ended without a receipt
    later = {**claim, 'attempt_no': claim['attempt_no'] + 1, 'fence_token': claim['fence_token'] + 1}
    local = PortalBindings(store, BASE, WORKER).persist_claim(later, 'Continue the closeout')['local_job_id']
    identity = AttemptIdentity(later['job_id'], WORKER, later['attempt_no'], later['fence_token'])
    lease2 = ExecutionLease(identity, clock=lambda: 100)
    server = datetime(2026, 9, 14, tzinfo=timezone.utc)
    lease2.acknowledge(identity, server_time=server, expires_at=server + timedelta(seconds=120), request_started=100)
    return config, store, local, later, lease2, args


def reobserved(config, store, local, args):
    """The same page facts read again in Chrome by the continued attempt."""
    import copy
    wf = Workflows(store, config)
    def again(oid):
        text = json.loads(store.one('SELECT payload FROM evidence WHERE id=?', (oid,))['payload'])['text']
        return wf.evidence(store.job(local), 'tool_observation', 'Chrome',
                           {'tool':'mcp__chrome__take_snapshot','text':text,'error':False}, True)['id']
    fresh = copy.deepcopy(args)
    for packet in fresh['pandadoc']:
        packet['observation_id'] = again(packet['observation_id'])
    fresh['folder']['observation_id'] = again(fresh['folder']['observation_id'])
    for item in fresh['files']:
        item['observation_id'] = again(item['observation_id'])
    return fresh


def report(config, store, local, lease2):
    bodies = []
    async def scenario():
        def handle(request):
            assert request.url.path.endswith('/clara-result')
            bodies.append(json.loads(request.content))
            return wire(CONTRACT.document['fixtures']['clara-result']['response'])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as api:
            transport = PortalTransport(BASE, lambda:'test', client=api, clock=lambda:100)
            reporter = PortalResults(config, store, transport, PortalJournal(store, BASE))
            try:
                return await reporter.deliver(PreparedAttempt(local, lease2, False), TIMING)
            finally:
                await reporter.close()
    return asyncio.run(scenario()), bodies[0]


def test_a_continued_attempt_that_recorded_delivery_again_hands_off_under_its_own_attempt(tmp_path):
    config, store, local, later, lease2, args = continued_attempt(tmp_path)
    proof = record_delivery(config, store, store.job(local), reobserved(config, store, local, args))
    assert proof['unresolved_operation_ids'] == [] and proof['reconciled_operation_ids'] == []
    store.status(local, 'needs_review')
    result, body = report(config, store, local, lease2)
    assert result['handoff']['status'] == 'ready_to_email'
    assert body['outcome'] == 'completed_prepared'
    assert (body['attempt_no'], body['fence_token']) == (later['attempt_no'], later['fence_token'])
    assert [a['kind'] for a in body['artifacts']] == ['pandadoc', 'onedrive_folder']
    assert all(a['observed_at'] > '2026' for a in body['artifacts'])


def test_a_continued_attempt_may_not_hand_off_the_readbacks_of_an_earlier_attempt(tmp_path):
    from clara.portal_results import REPEAT_DELIVERY
    config, store, local, later, lease2, args = continued_attempt(tmp_path)
    store.status(local, 'needs_review')  # finished without calling record_portal_delivery again
    result, body = report(config, store, local, lease2)
    assert body['outcome'] == 'needs_review' and body['artifacts'] == []
    assert body['needs_review_reason'] == REPEAT_DELIVERY
    assert 'record_portal_delivery in this attempt' in REPEAT_DELIVERY


def test_readbacks_older_than_the_portal_accepts_are_refused_locally(tmp_path, monkeypatch):
    import clara.portal_results as module
    config, store, job, lease, args = completed_delivery(tmp_path)
    real = module.time.time
    monkeypatch.setattr(module.time, 'time', lambda: real() + 13 * 3600)
    result, body = report(config, store, job['id'], lease)
    assert body['outcome'] == 'needs_review'
    assert body['needs_review_reason'] == module.STALE_DELIVERY
