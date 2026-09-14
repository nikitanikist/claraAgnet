import json
import time

import pytest

from clara.portal_documents import collect_documents
from clara.portal_outputs import record_delivery
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
    pid = observed(panda_url + ' packet-001 John Smith john@example.com case-2024')
    fid = observed(folder_url + ' folder-001 case-2024')
    args = {'document_evidence_ids':proofs,
            'pandadoc':[{'member_id':'m1','remote_id':'packet-001','url':panda_url,
                         'external_key':'case-2024','observation_id':pid}],
            'folder':{'remote_id':'folder-001','url':folder_url,'external_key':'case-2024','observation_id':fid},
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
                      (time.time()-301,args['files'][0]['observation_id']))
    elif change == 'malformed_identity':
        args['files'][0]['remote_file_id'] = {'unexpected':'object'}
    else:
        store.execute("UPDATE evidence SET kind='remote_record' WHERE id=?", (args['files'][0]['observation_id'],))
    with pytest.raises(ValueError):
        record_delivery(config, store, job, args)
    assert store.rows("SELECT id FROM evidence WHERE kind='portal_delivery'") == []
