import asyncio
import json
import time
from dataclasses import replace

import httpx
import pytest

from clara.instance import single_instance
from clara.portal_journal import PortalJournal
from clara.portal_recovery import saved_attempt
from clara.portal_results import PortalResults
from clara.portal_transport import PortalTransport, PortalUnavailable
from test_portal_delivery import BASE, CONTRACT, wire
from test_portal_results import completed_delivery


def recovery_package(tmp_path):
    config, store, job, lease, args = completed_delivery(tmp_path)
    binding = store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (job['id'],))
    store.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,?,?,?,NULL,NULL)',
        ('cycle', BASE, lease.identity.worker_id, 'held', binding['claim_json'], job['id'], time.time()))
    store.execute('UPDATE jobs SET usage=? WHERE id=?',
        (json.dumps({'version':2,'wall_duration_ms':42100,'user_wait_ms':2100,
                    'tokens':{'input_tokens':100,'output_tokens':50,
                              'cache_read_input_tokens':0,'cache_creation_input_tokens':0},
                    'sdk_estimated_usd':0.01,'coverage':'reported'}), job['id']))
    return config, store, job, lease, args


def test_saved_link_report_survives_lost_receipt_without_upload_or_model(tmp_path):
    config, store, job, lease, _ = recovery_package(tmp_path)
    assert saved_attempt(store, BASE, lease.identity) == job['id']
    lease.fence('Execution is over; recovery has no execution lease.')
    calls = []
    async def scenario():
        def handle(request):
            assert request.url.path.endswith('/clara-result')
            calls.append(json.loads(request.content))
            if len(calls) == 1:
                raise httpx.ReadError('Lost receipt', request=request)
            return wire(CONTRACT.document['fixtures']['clara-result']['response'])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            transport = PortalTransport(BASE, lambda:'test', client=client)
            reporter = PortalResults(config, store, transport, PortalJournal(store, BASE))
            try:
                with pytest.raises(PortalUnavailable):
                    await reporter.report_saved_closeout(lease.identity, job['id'])
                # Later timing or observations must not alter an already sent report.
                store.execute('UPDATE jobs SET usage=NULL WHERE id=?', (job['id'],))
                await reporter.report_saved_closeout(lease.identity, job['id'])
                assert calls[0] == calls[1]
                assert [a['kind'] for a in calls[0]['artifacts']] == ['pandadoc','onedrive_folder']
                assert calls[0]['usage']['active_seconds'] == 40
                assert calls[0]['usage']['waiting_seconds'] == 3
                assert len(store.rows('SELECT * FROM jobs')) == 1
                assert store.rows('SELECT * FROM portal_v1_uploads') == []
            finally:
                await reporter.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['unfinished', 'wrong_fence', 'wrong_job', 'other_active'])
def test_recovery_does_not_take_over_another_or_unfinished_execution(tmp_path, change):
    _, store, job, lease, _ = recovery_package(tmp_path)
    identity = lease.identity
    if change == 'unfinished':
        store.status(job['id'], 'interrupted')
    elif change == 'wrong_fence':
        identity = replace(identity, fence_token=identity.fence_token + 1)
    elif change == 'wrong_job':
        identity = replace(identity, job_id='99999999-9999-4999-8999-999999999999')
    else:
        store.create_job(job['conversation_id'], 'Other work', 'ask', [])
    with pytest.raises(ValueError):
        saved_attempt(store, BASE, identity)


@pytest.mark.parametrize('change', ['missing_timing', 'wrong_folder', 'missing_file', 'different_hash'])
def test_invalid_saved_delivery_cannot_be_sent(tmp_path, change):
    config, store, job, lease, _ = recovery_package(tmp_path)
    if change == 'missing_timing':
        store.execute('UPDATE jobs SET usage=NULL WHERE id=?', (job['id'],))
    else:
        row = store.one("SELECT id,payload FROM evidence WHERE job_id=? AND kind='portal_delivery'", (job['id'],))
        payload = json.loads(row['payload'])
        files = payload['artifacts'][-1]['evidence']['uploaded']
        if change == 'missing_file':
            files.pop()
        elif change == 'wrong_folder':
            files[0]['folder_id'] = 'other-folder'
        else:
            files[0]['sha256'] = '0'*64
        store.execute('UPDATE evidence SET payload=? WHERE id=?', (json.dumps(payload),row['id']))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:pytest.fail('Must not send'))) as client:
            reporter = PortalResults(config, store, PortalTransport(BASE, lambda:'test', client=client), PortalJournal(store, BASE))
            try:
                with pytest.raises(ValueError):
                    await reporter.report_saved_closeout(lease.identity, job['id'])
                assert store.rows("SELECT * FROM portal_v1_outbox WHERE operation='clara-result'") == []
            finally:
                await reporter.close()
    asyncio.run(scenario())


def test_recovery_lock_excludes_a_running_clara_service(tmp_path):
    with single_instance(tmp_path):
        with pytest.raises(RuntimeError, match='already running'):
            with single_instance(tmp_path):
                pytest.fail('A second process must not enter recovery.')
