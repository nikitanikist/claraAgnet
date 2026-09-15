"""Map observed remote delivery records to this portal's assigned family.

Observations establish what the worker read in Chrome. The portal independently
verifies stored bytes and PandaDoc before committing the email draft.
"""
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import urlsplit

from .knowledge import decode
from .portal_documents import collect_documents
from .portal_lease import AttemptIdentity
from .workflows import Workflows


def _text(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Provide a complete, bounded record identity from the observed page.')
    return value.strip()


def _remote_url(value, system):
    value = _text(value, 2000)
    u = urlsplit(value)
    host = (u.hostname or '').lower()
    allowed = (host == 'app.pandadoc.com' if system == 'pandadoc' else
               host in {'onedrive.live.com', '1drv.ms'} or host.endswith('.sharepoint.com'))
    if not allowed or u.scheme != 'https' or u.username or u.password or u.port not in (None, 443):
        raise ValueError('Use the record link on the expected PandaDoc or OneDrive service.')
    return value


def _observation(store, job, eid, values):
    proof = decode(store.one('SELECT * FROM evidence WHERE id=? AND job_id=?',
                             (_text(eid), job['id'])), 'payload')
    now = time.time()
    if (not proof or proof['kind'] != 'tool_observation' or proof['payload'].get('error')
            or not proof['payload'].get('tool', '').startswith('mcp__chrome__')
            or not max(job['created'], now - 300) <= proof['created'] <= now):
        raise ValueError('Read the remote record again in Chrome and use that fresh observation ID.')
    text = re.sub(r'\s+', ' ', str(proof['payload'].get('text', ''))).casefold()
    for value in values:
        if isinstance(value, int):
            if not any(re.search(r'(?<!\d)' + re.escape(v) + r'(?!\d)', text)
                       for v in (str(value), f'{value:,}')):
                raise ValueError('The exact file size in bytes must appear in the browser observation.')
        elif re.sub(r'\s+', ' ', _text(value, 2000)).casefold() not in text:
            raise ValueError('The record identity does not match the browser observation. Read the actual record again.')
    return proof


def record_delivery(config, store, job, args):
    row = store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (job['id'],))
    if not row:
        raise ValueError('This tool is available only for an assigned portal closeout.')
    claim = json.loads(row['claim_json'])
    if claim['kind'] != 'closeout':
        raise ValueError('Assign an eligible T1 closeout before recording delivery outputs.')
    identity = AttemptIdentity(row['external_job_id'], row['worker_id'], row['attempt_no'], row['fence_token'])
    documents = collect_documents(config, store, row['namespace'], identity, job['id'], args['document_evidence_ids'])
    members = {m['member_id']: m for m in claim['closeout']['members']}
    packets, files = args['pandadoc'], args['files']
    for records, fields in ((packets, ('member_id', 'remote_id', 'url', 'external_key', 'observation_id')),
                            (files, ('member_id', 'document_type', 'tax_year', 'remote_file_id', 'observation_id'))):
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise ValueError('Provide a list of complete observed delivery records.')
        for record in records:
            for field in fields:
                _text(record.get(field), 2000 if field == 'url' else 200)
    if not isinstance(args.get('folder'), dict):
        raise ValueError('Provide the observed OneDrive folder record.')
    for field in ('remote_id', 'url', 'external_key', 'observation_id'):
        _text(args['folder'].get(field), 2000 if field == 'url' else 200)
    if (not isinstance(packets, list) or not all(isinstance(p, dict) for p in packets)
            or len(packets) != len(members) or {p.get('member_id') for p in packets} != set(members)
            or len({p.get('remote_id') for p in packets}) != len(packets)):
        raise ValueError('Provide exactly one distinct PandaDoc packet for every assigned family member.')
    if not isinstance(files, list) or not all(isinstance(f, dict) for f in files) or len(files) != len(documents):
        raise ValueError('Provide an observed OneDrive record for every required PDF.')
    expected = {(d.member_id, d.document_type, d.tax_year): d for d in documents}
    if (len({(f.get('member_id'), f.get('document_type'), f.get('tax_year')) for f in files}) != len(files)
            or {(f.get('member_id'), f.get('document_type'), f.get('tax_year')) for f in files} != set(expected)
            or len({f.get('remote_file_id') for f in files}) != len(files)):
        raise ValueError('Each OneDrive record must identify a distinct member, document and remote file.')

    artifacts, packet_proofs = [], []
    for packet in packets:
        member = members[packet['member_id']]
        remote_id = _text(packet['remote_id'])
        url = _remote_url(packet['url'], 'pandadoc')
        observation = _observation(store, job, packet['observation_id'],
            [url, remote_id, member['member_name'], _text(member['member_email'], 320), _text(packet['external_key'])])
        packet_proofs.append((packet, member, observation))
        artifacts.append({'kind': 'pandadoc', 'member_id': member['member_id'],
                          'remote_id': remote_id, 'url': url, 'verification': 'worker_observed',
                          'observed_at': datetime.fromtimestamp(observation['created'], timezone.utc).isoformat(),
                          'evidence': {'observation_id': observation['id'], 'recipient_email': member['member_email']}})

    folder = args['folder']
    folder_id, folder_url = _text(folder['remote_id']), _remote_url(folder['url'], 'storage')
    folder_observation = _observation(store, job, folder['observation_id'],
                                      [folder_url, folder_id, _text(folder['external_key'])])
    uploaded = []
    for file in files:
        doc = expected[(file['member_id'], file['document_type'], file['tax_year'])]
        file_id = _text(file['remote_file_id'])
        observation = _observation(store, job, file['observation_id'],
                                   [folder_id, file_id, doc.file.name, len(doc.file.data)])
        uploaded.append({'member_id': doc.member_id, 'document_type': doc.document_type,
                         'tax_year': doc.tax_year, 'file_name': doc.file.name,
                         'bytes': len(doc.file.data), 'sha256': doc.file.sha256,
                         'remote_file_id': file_id, 'folder_id': folder_id,
                         'observed_at': datetime.fromtimestamp(observation['created'], timezone.utc).isoformat(),
                         'observation_id': observation['id']})
    artifacts.append({'kind': 'onedrive_folder', 'remote_id': folder_id, 'url': folder_url,
                      'verification': 'worker_observed',
                      'observed_at': datetime.fromtimestamp(folder_observation['created'], timezone.utc).isoformat(),
                      'evidence': {'uploaded': uploaded, 'provenance': 'worker_observed_chrome',
                                   'coverage': 'Remote names, sizes and IDs observed in Chrome; hashes identify local source PDFs.'}})

    # The complete set passed. These proofs support checkpoints, not approval.
    wf = Workflows(store, config)
    signing = []
    for packet, member, observation in packet_proofs:
        signing.append(wf.evidence(job, 'remote_record', packet['remote_id'], {
            'system': 'pandadoc', 'remote_id': packet['remote_id'], 'url': packet['url'],
            'client_name': member['member_name'], 'external_key': packet['external_key'],
            'observation_id': observation['id'], 'case_key': claim['closeout']['closeout_form_id'],
            'coverage': 'Worker-observed packet and recipient; portal verification still required.'}, True)['id'])
    storage = wf.evidence(job, 'remote_record', folder_id, {
        'system': 'storage', 'remote_id': folder_id, 'url': folder_url,
        'external_key': folder['external_key'], 'observation_id': folder_observation['id'],
        'case_key': claim['closeout']['closeout_form_id'], 'uploaded': uploaded,
        'coverage': 'Worker-observed Chrome records; not independent OneDrive API verification.'}, True)
    proof = wf.evidence(job, 'portal_delivery', identity.job_id, {
        'attempt_no': identity.attempt_no, 'fence_token': identity.fence_token,
        'document_evidence_ids': args['document_evidence_ids'], 'artifacts': artifacts}, True)
    return {'delivery_evidence_id': proof['id'], 'signature_evidence_ids': signing,
            'storage_evidence_id': storage['id'],
            'next': 'Reconcile reserved writes with matching proofs and save the remaining checkpoints. The staff member who assigned this closeout to Clara receives it in Ready to Email for review.'}
