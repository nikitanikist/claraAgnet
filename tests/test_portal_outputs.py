import asyncio
import json
import re
import time

import pytest

from clara.operations import Operations
from clara.portal_documents import collect_documents
from clara.portal_outputs import closeout_reservation_keys, closeout_reservations, record_delivery
from clara.production_tools import definitions
from clara.workflows import Workflows
from test_portal_documents import package
from test_portal_delivery import BASE


def delivery(tmp_path):
    config, store, job, lease, proofs = package(tmp_path)
    wf = Workflows(store, config)
    docs = collect_documents(config, store, BASE, lease.identity, job['id'], proofs)
    panda_url = 'https://app.pandadoc.com/a/#/documents/packet-001'
    folder_url = 'https://example.sharepoint.com/sites/clients/Smith'
    def observed(text):
        return wf.evidence(job, 'tool_observation', 'Chrome',
                           {'tool':'mcp__chrome__take_snapshot','text':text,'error':False}, True)['id']
    claim = json.loads(store.one('SELECT claim_json FROM portal_v1_attempts WHERE local_job_id=?', (job['id'],))['claim_json'])
    keys = closeout_reservation_keys(claim)
    # Pages never show the canonical reservation keys; the packet and folder readbacks carry only page facts.
    pid = observed(panda_url + ' packet-001 John Smith john@example.com')
    fid = observed(folder_url + ' folder-001')
    args = {'document_evidence_ids':proofs,
            'pandadoc':[{'member_id':'m1','remote_id':'packet-001','url':panda_url,
                         'external_key':keys['pandadoc']['m1'],'observation_id':pid}],
            'folder':{'remote_id':'folder-001','url':folder_url,'external_key':keys['storage']['folder'],'observation_id':fid},
            'files':[]}
    for n, doc in enumerate(docs):
        oid = observed(f'folder-001 file-{n} {doc.file.name} {len(doc.file.data):,} bytes')
        args['files'].append({'member_id':doc.member_id,'document_type':doc.document_type,
                              'tax_year':doc.tax_year,'remote_file_id':f'file-{n}','observation_id':oid})
    return config, store, job, lease, args


def test_delivery_binds_exact_family_and_remote_files_as_worker_observed(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    result = record_delivery(config, store, job, args)
    saved = json.loads(store.one('SELECT payload FROM evidence WHERE id=?', (result['delivery_evidence_id'],))['payload'])
    assert saved['attempt_no'] == lease.identity.attempt_no
    assert saved['fence_token'] == lease.identity.fence_token
    assert [a['kind'] for a in saved['artifacts']] == ['pandadoc','onedrive_folder']
    assert all(a['verification'] == 'worker_observed' for a in saved['artifacts'])
    files = saved['artifacts'][1]['evidence']['uploaded']
    assert len(files) == 3 and len({f['remote_file_id'] for f in files}) == 3
    assert all(f['bytes'] > 0 and len(f['sha256']) == 64 for f in files)
    assert len(result['signature_evidence_ids']) == 1 and result['storage_evidence_id']
    assert Workflows(store, config).get(job['conversation_id'])['status'] == 'active'


@pytest.mark.parametrize('change', ['wrong_recipient', 'duplicate_file', 'missing_file', 'stale_observation', 'assistant_claim', 'malformed_identity'])
def test_unmatched_or_unobserved_delivery_cannot_be_registered(tmp_path, change):
    config, store, job, lease, args = delivery(tmp_path)
    if change == 'wrong_recipient':
        eid = args['pandadoc'][0]['observation_id']
        row = store.one('SELECT payload FROM evidence WHERE id=?', (eid,))
        data = json.loads(row['payload'])
        data['text'] = data['text'].replace('john@example.com','other@example.com')
        store.execute('UPDATE evidence SET payload=? WHERE id=?', (json.dumps(data),eid))
    elif change == 'duplicate_file':
        args['files'][1]['remote_file_id'] = args['files'][0]['remote_file_id']
    elif change == 'missing_file':
        args['files'].pop()
    elif change == 'stale_observation':
        store.execute('UPDATE evidence SET created=? WHERE id=?',
                      (time.time()-1201,args['files'][0]['observation_id']))
    elif change == 'malformed_identity':
        args['files'][0]['remote_file_id'] = {'unexpected':'object'}
    else:
        store.execute("UPDATE evidence SET kind='remote_record' WHERE id=?", (args['files'][0]['observation_id'],))
    with pytest.raises(ValueError):
        record_delivery(config, store, job, args)
    assert store.rows("SELECT id FROM evidence WHERE kind='portal_delivery'") == []


def test_delivery_reconciles_canonical_reservations_and_reports_leftovers(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    claim = json.loads(store.one('SELECT claim_json FROM portal_v1_attempts WHERE local_job_id=?', (job['id'],))['claim_json'])
    keys = closeout_reservation_keys(claim)
    form = claim['closeout']['closeout_form_id']
    assert keys == {'pandadoc': {'m1': f'closeout:{form}:pandadoc:m1'}, 'storage': {'folder': f'closeout:{form}:storage:folder'}}
    assert closeout_reservations(claim) == [('pandadoc', 'create_signature_packet', keys['pandadoc']['m1']),
                                            ('storage', 'create_folder', keys['storage']['folder'])]
    ops = Operations(store)
    packet = ops.reserve(job, 'pandadoc', 'create_signature_packet', keys['pandadoc']['m1'], {})
    folder = ops.reserve(job, 'storage', 'create_folder', keys['storage']['folder'], {})
    drifted = ops.reserve(job, 'pandadoc', 'create_signature_packet', 'John Smith T1 2024 - packet (v2)', {})
    # The canonical key under another operation name is a different write and is never confirmed by delivery.
    renamed = ops.reserve(job, 'pandadoc', 'send_document', keys['pandadoc']['m1'], {})
    result = record_delivery(config, store, job, args)
    signing = json.loads(store.one('SELECT payload FROM evidence WHERE id=?', (result['signature_evidence_ids'][0],))['payload'])
    storage = json.loads(store.one('SELECT payload FROM evidence WHERE id=?', (result['storage_evidence_id'],))['payload'])
    assert signing['external_key'] == keys['pandadoc']['m1'] == signing['reservation_key']
    assert storage['external_key'] == keys['storage']['folder'] == storage['reservation_key']
    assert sorted(result['reconciled_operation_ids']) == sorted([packet['id'], folder['id']])
    assert result['unresolved_operation_ids'] == [drifted['id'], renamed['id']]
    assert drifted['id'] in result['next'] and renamed['id'] in result['next']
    for op, eid, remote in ((packet, result['signature_evidence_ids'][0], 'packet-001'), (folder, result['storage_evidence_id'], 'folder-001')):
        row = store.one('SELECT * FROM operations WHERE id=?', (op['id'],))
        assert row['state'] == 'confirmed' and row['remote_id'] == remote
        assert json.loads(row['result']) == {'evidence_id': eid, 'auto': 'record_portal_delivery'}
    for op in (drifted, renamed):
        assert store.one('SELECT state FROM operations WHERE id=?', (op['id'],))['state'] == 'uncertain'
    again = record_delivery(config, store, job, args)
    assert again['reconciled_operation_ids'] == [] and again['unresolved_operation_ids'] == [drifted['id'], renamed['id']]
    assert len(store.rows('SELECT id FROM operations')) == 4
    assert json.loads(store.one('SELECT result FROM operations WHERE id=?', (packet['id'],))['result'])['evidence_id'] == result['signature_evidence_ids'][0]


def test_delivery_result_survives_a_failing_auto_reconcile(tmp_path, monkeypatch):
    config, store, job, lease, args = delivery(tmp_path)
    claim = json.loads(store.one('SELECT claim_json FROM portal_v1_attempts WHERE local_job_id=?', (job['id'],))['claim_json'])
    keys = closeout_reservation_keys(claim)
    ops = Operations(store)
    packet = ops.reserve(job, 'pandadoc', 'create_signature_packet', keys['pandadoc']['m1'], {})
    folder = ops.reserve(job, 'storage', 'create_folder', keys['storage']['folder'], {})
    def broken(self, job, oid, evidence_id, auto=None):
        raise ValueError('Evidence does not match this reserved operation.')
    monkeypatch.setattr(Operations, 'reconcile', broken)
    result = record_delivery(config, store, job, args)
    assert result['reconciled_operation_ids'] == [] and result['unresolved_operation_ids'] == [packet['id'], folder['id']]
    assert store.one('SELECT id FROM evidence WHERE id=?', (result['delivery_evidence_id'],))
    assert {r['state'] for r in store.rows('SELECT state FROM operations')} == {'uncertain'}


def test_portal_closeout_reservation_accepts_only_canonical_triples(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    claim = json.loads(store.one('SELECT claim_json FROM portal_v1_attempts WHERE local_job_id=?', (job['id'],))['claim_json'])
    keys = closeout_reservation_keys(claim)
    reserve = next(fn for name, _, _, fn in definitions(config, store, job) if name == 'reserve_external_write')
    assert asyncio.run(reserve({'system':'pandadoc','operation':'create_signature_packet','key':keys['pandadoc']['m1'],'request':{}}))['execute_allowed']
    assert asyncio.run(reserve({'system':'storage','operation':'create_folder','key':keys['storage']['folder'],'request':{}}))['execute_allowed']
    listed = 'pandadoc create_signature_packet ' + keys['pandadoc']['m1'] + '; storage create_folder ' + keys['storage']['folder']
    for system, operation, key in (('pandadoc', 'create_signature_packet', 'John Smith T1 2024 packet'),
                                   ('storage', 'create_folder', keys['pandadoc']['m1']),
                                   ('pandadoc', 'send_document', keys['pandadoc']['m1']),
                                   ('storage', 'upload_file', keys['storage']['folder']),
                                   ('sharepoint', 'create_folder', 'anything')):
        with pytest.raises(ValueError, match=listed):
            asyncio.run(reserve({'system':system,'operation':operation,'key':key,'request':{}}))
    with pytest.raises(ValueError, match='Supply system, operation and stable business key'):
        asyncio.run(reserve({'system':['pandadoc'],'operation':'create_signature_packet','key':keys['pandadoc']['m1'],'request':{}}))
    assert len(store.rows('SELECT id FROM operations')) == 2
    other = store.create_job(store.create_conversation()['id'], 'Not a portal task', 'ask', [])
    plain = next(fn for name, _, _, fn in definitions(config, store, other) if name == 'reserve_external_write')
    assert asyncio.run(plain({'system':'pandadoc','operation':'create','key':'free-form key','request':{}}))['execute_allowed']


def _payload_text(store, eid):
    row = store.one('SELECT payload FROM evidence WHERE id=?', (eid,))
    return json.loads(row['payload'])['text']


def _set_text(store, eid, text):
    row = store.one('SELECT payload FROM evidence WHERE id=?', (eid,))
    data = json.loads(row['payload']); data['text'] = text
    store.execute('UPDATE evidence SET payload=? WHERE id=?', (json.dumps(data), eid))


def test_business_keys_are_bound_by_reservations_not_by_page_text(tmp_path):
    # A PandaDoc page or OneDrive folder never shows closeout:<form>:... keys, and the
    # model cannot substitute a key of its own for the canonical one.
    config, store, job, lease, args = delivery(tmp_path)
    claim = json.loads(store.one('SELECT claim_json FROM portal_v1_attempts WHERE local_job_id=?', (job['id'],))['claim_json'])
    keys = closeout_reservation_keys(claim)
    for eid in (args['pandadoc'][0]['observation_id'], args['folder']['observation_id']):
        assert 'closeout:' not in _payload_text(store, eid)
    result = record_delivery(config, store, job, args)
    signing = json.loads(store.one('SELECT payload FROM evidence WHERE id=?', (result['signature_evidence_ids'][0],))['payload'])
    assert signing['external_key'] == keys['pandadoc']['m1'] == signing['reservation_key']
    for record, expected in ((args['pandadoc'][0], keys['pandadoc']['m1']), (args['folder'], keys['storage']['folder'])):
        record['external_key'] = 'John Smith T1 2024 - packet (v2)'
        with pytest.raises(ValueError, match='canonical reservation key ' + re.escape(expected)):
            record_delivery(config, store, job, args)
        record['external_key'] = expected


def test_encoded_url_spellings_match_case_insensitively(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    fid = args['folder']['observation_id']
    args['folder']['url'] = 'https://example.sharepoint.com/personal/laureen/Documents/Müller {2024}'
    _set_text(store, fid, 'https://example.sharepoint.com/personal/laureen/documents/m%c3%bcller%20%7b2024%7d folder-001')
    assert record_delivery(config, store, job, args)['storage_evidence_id']


def test_observations_within_twenty_minutes_and_encoded_urls_are_accepted(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    fid = args['folder']['observation_id']
    args['folder']['url'] = 'https://example.sharepoint.com/personal/laureen/Documents/CH Clients Share/CLARA-TEST/'
    _set_text(store, fid, 'https://example.sharepoint.com/personal/laureen/Documents/CH%20Clients%20Share/CLARA-TEST folder-001')
    # A readback from earlier in this task (15 minutes ago) is still usable.
    store.execute('UPDATE jobs SET created=? WHERE id=?', (time.time() - 1000, job['id']))
    store.execute('UPDATE evidence SET created=? WHERE id=?', (time.time() - 900, args['files'][0]['observation_id']))
    result = record_delivery(config, store, store.job(job['id']), args)
    assert result['storage_evidence_id']


@pytest.mark.parametrize('change, expected', [
    ('wrong_document_type', 'm1/client_copy/2024'),
    ('missing_packet', 'member_id (m1)'),
    ('rounded_size', 'exact OneDrive file size'),
    ('wrong_url', 'shows the PandaDoc packet value "https://app.pandadoc.com/a/#/documents/packet-999"'),
    ('malformed_field', 'bounded remote_file_id'),
])
def test_rejections_name_what_the_model_must_correct(tmp_path, change, expected):
    config, store, job, lease, args = delivery(tmp_path)
    if change == 'wrong_document_type':
        args['files'][0]['document_type'] = 'client-copy'
    elif change == 'missing_packet':
        args['pandadoc'] = []
    elif change == 'rounded_size':
        oid = args['files'][0]['observation_id']
        _set_text(store, oid, ' '.join(w for w in _payload_text(store, oid).split() if not w[0].isdigit()) + ' 245 KB')
    elif change == 'wrong_url':
        args['pandadoc'][0]['url'] = 'https://app.pandadoc.com/a/#/documents/packet-999'
    else:
        args['files'][0]['remote_file_id'] = ''
    with pytest.raises(ValueError) as failure:
        record_delivery(config, store, job, args)
    assert expected in str(failure.value)
    assert store.rows("SELECT id FROM evidence WHERE kind='portal_delivery'") == []


def test_a_record_may_span_a_navigation_readback_and_a_snapshot(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    wf = Workflows(store, config)
    def observed(tool, text):
        return wf.evidence(job, 'tool_observation', 'Chrome', {'tool': tool, 'text': text, 'error': False}, True)['id']
    # chrome-devtools-mcp: navigate_page prints the URL, take_snapshot prints the page without it.
    nav = observed('mcp__chrome__navigate_page', 'Successfully navigated to https://app.pandadoc.com/a/#/documents/packet-001')
    snap = observed('mcp__chrome__take_snapshot', 'uid=1 heading "2024 T1 John Smith T183" uid=2 John Smith john@example.com Signer')
    args['pandadoc'][0]['observation_id'] = snap
    result = record_delivery(config, store, job, args)
    saved = json.loads(store.one('SELECT payload FROM evidence WHERE id=?', (result['delivery_evidence_id'],))['payload'])
    assert set(saved['artifacts'][0]['evidence']['observation_ids']) == {snap, nav}
    signing = json.loads(store.one('SELECT payload FROM evidence WHERE id=?', (result['signature_evidence_ids'][0],))['payload'])
    assert signing['observation_id'] == snap and set(signing['observation_ids']) == {snap, nav}


def test_values_missing_from_every_fresh_readback_are_named(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    args['pandadoc'][0]['remote_id'] = 'packet-777'
    with pytest.raises(ValueError, match='No fresh Chrome readback from this task shows the PandaDoc packet value "packet-777"'):
        record_delivery(config, store, job, args)


@pytest.mark.parametrize('change', ['encoded_id', 'id_prefix', 'url_prefix', 'name_prefix'])
def test_spelling_tolerance_applies_to_urls_only_and_never_to_prefixes(tmp_path, change):
    config, store, job, lease, args = delivery(tmp_path)
    if change == 'encoded_id':
        args['pandadoc'][0]['remote_id'] = 'packet%2D001'   # decodes to packet-001; an ID is matched verbatim
    elif change == 'id_prefix':
        _set_text(store, args['files'][0]['observation_id'],
                  _payload_text(store, args['files'][0]['observation_id']).replace('file-0 ', 'file-01 '))
    elif change == 'url_prefix':
        _set_text(store, args['folder']['observation_id'], 'https://example.sharepoint.com/sites/clients/Smithson folder-001')
    else:
        _set_text(store, args['pandadoc'][0]['observation_id'],
                  _payload_text(store, args['pandadoc'][0]['observation_id']).replace('John Smith ', 'John Smithson '))
    with pytest.raises(ValueError, match='No fresh Chrome readback'):
        record_delivery(config, store, job, args)


def test_sharp_s_and_upper_case_escapes_still_match_an_encoded_page(tmp_path):
    config, store, job, lease, args = delivery(tmp_path)
    args['folder']['url'] = 'https://example.sharepoint.com/personal/laureen/Documents/Straße {2024}/'
    _set_text(store, args['folder']['observation_id'],
              'Title (https://example.sharepoint.com/personal/laureen/Documents/Stra%C3%9Fe%20%7B2024%7D) folder-001')
    assert record_delivery(config, store, job, args)['storage_evidence_id']
