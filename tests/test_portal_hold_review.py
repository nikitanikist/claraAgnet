import asyncio
from dataclasses import asdict
import json
import time

import httpx
import pytest

from clara import portal_hold_review as review
from clara.portal_journal import PortalJournal
from clara.portal_transport import PortalTransport
from test_portal_delivery import BASE, CONTRACT, wire
from test_portal_recovery import recovery_package


def package(tmp_path):
    config, store, job, lease, _ = recovery_package(tmp_path)
    import sqlite3
    with store.connect() as source, sqlite3.connect(config.data / 'clara.sqlite3') as target:
        source.backup(target)
    store = review.Store(config.data / 'clara.sqlite3')
    identity = lease.identity
    evidence = store.one("SELECT * FROM evidence WHERE job_id=? AND kind='portal_delivery'", (job['id'],))
    artifacts = json.loads(evidence['payload'])['artifacts']
    receipt = CONTRACT.document['fixtures']['clara-result']['response']
    journal = PortalJournal(store, BASE)
    staged = journal.stage(identity, 'clara-result', 'result-' + job['id'],
                           {**asdict(identity), 'outcome':'completed_prepared', 'artifacts': artifacts})
    journal.acknowledge(staged['id'], receipt)
    (config.data / 'portal.json').write_text(json.dumps({'enabled':True,'protocol_version':1,
        'base_url':BASE,'worker_id':identity.worker_id,'token_env':'CLARA_PORTAL_TEST',
        'authentication_reviewed':True,'windows_handoff':{'exclusive_session':True,'qualified':False}}))
    return config, store, job, identity


def snapshot():
    return {'version':1,'errors':[],'interactive':True,'observed_at':time.time(),
            'boot':100.,'session':1,'controller':[7,101.], 'owner':'a'*64,
            'processes':[{'pid':7,'created':101.,'name':'python.exe'}],
            'windows':[],'ancestors':[7], 'print_jobs':[]}


def test_review_releases_only_completed_slot_preserving_original_baseline(tmp_path, monkeypatch):
    config, store, job, identity = package(tmp_path)
    store.execute('INSERT INTO portal_windows_baselines VALUES(?,?)', (job['id'], '{"old":true}'))
    requests = []
    def handler(request):
        requests.append(request.url.path)
        assert request.url.path.endswith('/clara-quiesce')
        body = json.loads(request.content)
        assert body['job_id'] == identity.job_id and body['report']['complete']
        return wire({**CONTRACT.document['fixtures']['clara-quiesce']['response'],
                     'quiescent':True, 'recovery_hold':False})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(review, 'PortalTransport', lambda base, provider: PortalTransport(base, lambda:'test', client=client))
            observations = []
            async def probe():
                value = snapshot()
                value['processes'].append({'pid':80 + len(observations),'created':102.,'name':'conhost.exe'})
                observations.append(value)
                return value
            async def pause(seconds): assert seconds == 3
            result = await review.release(config, identity, {}, 'Operator checked completed outputs and idle dedicated desktop.', probe=probe,pause=pause)
            assert result['released'] and not result['task_restarted']
    asyncio.run(scenario())
    assert len(requests) == 1
    assert store.one('SELECT state FROM portal_v1_cycles')['state'] == 'reconciled'
    assert store.one('SELECT snapshot FROM portal_windows_baselines')['snapshot'] == '{"old":true}'
    assert len(store.rows('SELECT * FROM jobs')) == 1
    assert store.job(job['id'])['status'] == 'needs_review'


@pytest.mark.parametrize('change',['result_missing','not_ready','active_job','unreturned_tool','unreviewed_operation'])
def test_review_blocks_unresolved_work_without_network(tmp_path, monkeypatch, change):
    config, store, job, identity = package(tmp_path)
    if change == 'result_missing':
        store.execute('DELETE FROM portal_v1_outbox')
    elif change == 'not_ready':
        store.execute("UPDATE portal_v1_outbox SET receipt=?", (json.dumps({'job_state':'needs_review'}),))
    elif change == 'active_job':
        store.create_job(job['conversation_id'], 'Other task', 'ask', [])
    elif change == 'unreturned_tool':
        store.event(job['conversation_id'],job['id'],'tool',{'id':'unreturned','name':'PowerShell'})
    else:
        from clara.operations import Operations
        Operations(store).reserve(job,'pandadoc','create_signature_packet','key',{})
    monkeypatch.setattr(review,'PortalTransport',lambda *a,**k: pytest.fail('No network before review passes'))
    async def scenario():
        async def probe(): return snapshot()
        async def pause(seconds): pass
        with pytest.raises(ValueError):
            await review.release(config,identity,{},'Operator inspected completed output and the desktop.',probe=probe,pause=pause)
    asyncio.run(scenario())
    assert store.one('SELECT finished FROM portal_v1_cycles')['finished'] is None


@pytest.mark.parametrize('change',['printer','task_app','executor','locked','incomplete'])
def test_native_activity_cannot_be_waved_through(change):
    value = snapshot()
    if change == 'printer': value['print_jobs'] = [{'queue':'x','id':1}]
    if change == 'task_app': value['processes'].append({'pid':8,'created':102.,'name':'t1txp.exe'})
    if change == 'executor': value['processes'].append({'pid':8,'created':102.,'name':'claude.exe'})
    if change == 'locked': value['interactive'] = False
    if change == 'incomplete': value['errors'] = ['unreadable']
    with pytest.raises(ValueError): review.check_desktop(value)


def test_unrelated_chat_window_does_not_block_reviewed_completed_task():
    value = snapshot()
    value['processes'].append({'pid':8,'created':102.,'name':'Messenger.exe'})
    value['windows'] = [{'handle':80,'class':'TSoftrosLANMessenger','pid':8}]
    review.check_desktop(value)


@pytest.mark.parametrize('wrong', [False, True])
def test_operator_mapping_requires_actual_delivered_packet_evidence(tmp_path, wrong):
    from clara.operations import Operations
    config, store, job, identity = package(tmp_path)
    op = Operations(store).reserve(job, 'pandadoc', 'create_signature_packet', 'stable-business-key', {})
    proof = store.one("SELECT * FROM evidence WHERE job_id=? AND kind='remote_record' AND payload LIKE '%pandadoc%'", (job['id'],))
    assert proof
    payload = json.loads(proof['payload'])
    payload['external_key'] = 'Different human document title'
    if wrong: payload['remote_id'] = 'not-the-delivered-packet'
    store.execute('UPDATE evidence SET payload=?,created=? WHERE id=?', (json.dumps(payload),time.time(),proof['id']))
    if wrong:
        with pytest.raises(ValueError): review.reviewed_operations(store, BASE, identity, job['id'], {op['id']:proof['id']})
    else:
        rows = review.reviewed_operations(store, BASE, identity, job['id'], {op['id']:proof['id']})
        assert rows[0]['reserved_key'] == 'stable-business-key'
        assert rows[0]['observed_key'] == 'Different human document title'
        assert store.one('SELECT state FROM operations WHERE id=?',(op['id'],))['state'] == 'uncertain'


@pytest.mark.parametrize('case', ['folder', 'packet_as_folder', 'folder_as_packet', 'other_system'])
def test_operator_mapping_binds_storage_reservation_only_to_the_delivered_folder(tmp_path, case):
    from clara.operations import Operations
    config, store, job, identity = package(tmp_path)
    folder_proof = store.one("SELECT * FROM evidence WHERE job_id=? AND kind='remote_record' AND payload LIKE '%\"system\": \"storage\"%'", (job['id'],))
    packet_proof = store.one("SELECT * FROM evidence WHERE job_id=? AND kind='remote_record' AND payload LIKE '%pandadoc%'", (job['id'],))
    assert folder_proof and packet_proof
    folder_id = json.loads(folder_proof['payload'])['remote_id']
    system = 'sharepoint' if case == 'other_system' else 'storage'
    op = Operations(store).reserve(job, system, 'create_folder', 'CLARA-TEST-reserved-folder-key', {})
    for proof in (folder_proof, packet_proof):
        store.execute('UPDATE evidence SET created=? WHERE id=?', (time.time(), proof['id']))
    if case == 'folder':
        rows = review.reviewed_operations(store, BASE, identity, job['id'], {op['id']: folder_proof['id']})
        assert rows[0]['remote_id'] == folder_id
        assert rows[0]['reserved_key'] == 'CLARA-TEST-reserved-folder-key'
        assert rows[0]['observed_key'] == json.loads(folder_proof['payload'])['external_key']
        assert store.one('SELECT state FROM operations WHERE id=?', (op['id'],))['state'] == 'uncertain'
        return
    if case == 'folder_as_packet':
        # A PandaDoc reservation can never be satisfied by the folder evidence.
        Operations(store).confirm_absence(op['id'], 'Test: retire the storage reservation before the packet case.')
        op = Operations(store).reserve(job, 'pandadoc', 'create_signature_packet', 'packet-key', {})
        mapping = {op['id']: folder_proof['id']}
    else:
        mapping = {op['id']: packet_proof['id']}
    with pytest.raises(ValueError):
        review.reviewed_operations(store, BASE, identity, job['id'], mapping)


@pytest.mark.parametrize('outcome', ['held', 'lost'])
def test_missing_release_confirmation_keeps_local_hold(tmp_path, monkeypatch, outcome):
    config, store, job, identity = package(tmp_path)
    def handler(request):
        if outcome == 'lost': raise httpx.ReadError('Receipt lost',request=request)
        return wire({**CONTRACT.document['fixtures']['clara-quiesce']['response'],
                     'quiescent':False,'recovery_hold':True})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(review,'PortalTransport',lambda base,provider:PortalTransport(base,lambda:'test',client=client))
            async def probe(): return snapshot()
            async def pause(seconds): pass
            with pytest.raises((ValueError,review.PortalUnavailable)):
                await review.release(config,identity,{},'Operator inspected finished outputs and dedicated desktop.',probe=probe,pause=pause)
    asyncio.run(scenario())
    assert store.one('SELECT finished FROM portal_v1_cycles')['finished'] is None
    assert len(store.rows('SELECT * FROM jobs')) == 1


def test_review_ignores_programs_that_were_open_before_the_task():
    baseline = snapshot()
    baseline['processes'] += [{'pid': 8, 'created': 102., 'name': 'chrome.exe', 'parent': 3},
                              {'pid': 9, 'created': 103., 'name': 't1txp.exe', 'parent': 3}]
    value = snapshot()
    value['processes'] += [{'pid': 8, 'created': 102., 'name': 'chrome.exe', 'parent': 3},
                           {'pid': 9, 'created': 103., 'name': 't1txp.exe', 'parent': 3},
                           {'pid': 12, 'created': 300., 'name': 'chrome.exe', 'parent': 8}]  # the browser's own helper
    review.check_desktop(value, baseline)
    with pytest.raises(ValueError):
        review.check_desktop(value)  # without the task's baseline nothing can be attributed
    value['processes'].append({'pid': 13, 'created': 301., 'name': 't1txp.exe', 'parent': 7})
    with pytest.raises(ValueError):
        review.check_desktop(value, baseline)
