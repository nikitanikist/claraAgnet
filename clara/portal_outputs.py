"""Map observed remote delivery records to this portal's assigned family.

Observations establish what the worker read in Chrome. The portal independently
verifies stored bytes and PandaDoc before committing the email draft.
"""
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import quote, unquote, urlsplit

from .knowledge import decode, job_scope
from .operations import Operations
from .portal_documents import collect_documents
from .portal_lease import AttemptIdentity
from .workflows import Workflows


def _text(value, limit=200, field='record identity'):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Provide a complete, bounded {field} from the observed page (text of 1-{limit} characters).')
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


CLOSEOUT_OPERATIONS = {'pandadoc': 'create_signature_packet', 'storage': 'create_folder'}


def closeout_reservation_keys(claim):
    """Canonical external-write keys for one assigned closeout, independent of page titles or timestamps."""
    closeout = claim['closeout']
    prefix = 'closeout:' + closeout['closeout_form_id']
    return {'pandadoc': {m['member_id']: f"{prefix}:pandadoc:{m['member_id']}" for m in closeout['members']},
            'storage': {'folder': prefix + ':storage:folder'}}


def closeout_reservations(claim):
    """The (system, operation, key) triples a portal closeout may reserve; no other write is accepted."""
    keys = closeout_reservation_keys(claim)
    return [(system, CLOSEOUT_OPERATIONS[system], key) for system in ('pandadoc', 'storage') for key in keys[system].values()]


# A delivery binds nine or more separate Chrome readbacks (two packets, the
# folder and six files). Five minutes forced the model to re-read everything
# whenever one call was rejected; this window still keeps every proof inside
# the current attempt.
FRESH_OBSERVATION_S = 1200


def _spellings(value):
    """Ways a page may spell the same URL or identifier: percent-encoded, decoded, with or without a trailing slash."""
    base = re.sub(r'\s+', ' ', value).casefold()
    forms = set()
    for text in (base, base.rstrip('/')):
        forms.update({text, unquote(text), quote(text, safe=":/#?&=%+@!$,;()*[]~'")})
    return {form for form in forms if form}


def _observation(store, job, eid, values, what='record'):
    proof = decode(store.one('SELECT * FROM evidence WHERE id=? AND job_id=?',
                             (_text(eid, field='observation_id'), job['id'])), 'payload')
    now = time.time()
    if (not proof or proof['kind'] != 'tool_observation' or proof['payload'].get('error')
            or not proof['payload'].get('tool', '').startswith('mcp__chrome__')
            or not max(job['created'], now - FRESH_OBSERVATION_S) <= proof['created'] <= now):
        raise ValueError(f'Read the {what} again in Chrome and use that fresh observation ID '
                         f'(a successful Chrome readback from this task, at most {FRESH_OBSERVATION_S // 60} minutes old).')
    text = re.sub(r'\s+', ' ', str(proof['payload'].get('text', ''))).casefold()
    for value in values:
        if isinstance(value, int):
            if not any(re.search(r'(?<!\d)' + re.escape(v) + r'(?!\d)', text)
                       for v in (str(value), f'{value:,}')):
                raise ValueError(f'The {what} observation does not show the exact file size {value} bytes. '
                                 'Read the item details or the storage API; a rounded size like "245 KB" is not enough.')
        elif not any(form in text for form in _spellings(_text(value, 2000))):
            shown = value if len(value) <= 120 else value[:117] + '...'
            raise ValueError(f'The {what} observation does not show "{shown}". Read the actual record again '
                             'and pass the values exactly as they appear there.')
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
    keys = closeout_reservation_keys(claim)
    packets, files = args['pandadoc'], args['files']
    for records, fields in ((packets, ('member_id', 'remote_id', 'url', 'external_key', 'observation_id')),
                            (files, ('member_id', 'document_type', 'tax_year', 'remote_file_id', 'observation_id'))):
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise ValueError('Provide a list of complete observed delivery records.')
        for record in records:
            for field in fields:
                _text(record.get(field), 2000 if field == 'url' else 200, field)
    if not isinstance(args.get('folder'), dict):
        raise ValueError('Provide the observed OneDrive folder record.')
    for field in ('remote_id', 'url', 'external_key', 'observation_id'):
        _text(args['folder'].get(field), 2000 if field == 'url' else 200, 'folder ' + field)
    if (len(packets) != len(members) or {p['member_id'] for p in packets} != set(members)
            or len({p['remote_id'] for p in packets}) != len(packets)):
        raise ValueError('pandadoc needs exactly one packet, each with a distinct remote_id, per member_id ('
                         + ', '.join(sorted(members)) + '); received member_id: '
                         + (', '.join(p['member_id'] for p in packets) or 'none') + '.')
    expected = {(d.member_id, d.document_type, d.tax_year): d for d in documents}
    received = [(f['member_id'], f['document_type'], f['tax_year']) for f in files]
    if sorted(received) != sorted(expected) or len({f['remote_file_id'] for f in files}) != len(files):
        raise ValueError('files needs exactly these member_id/document_type/tax_year records, each with a distinct '
                         'remote_file_id: ' + ', '.join('/'.join(k) for k in sorted(expected))
                         + '; received: ' + (', '.join('/'.join(k) for k in received) or 'none') + '.')

    artifacts, packet_proofs = [], []
    for packet in packets:
        member = members[packet['member_id']]
        remote_id = _text(packet['remote_id'])
        url = _remote_url(packet['url'], 'pandadoc')
        # The reservation records bind the business key; a page never shows it.
        observation = _observation(store, job, packet['observation_id'],
            [url, remote_id, member['member_name'], _text(member['member_email'], 320)], 'PandaDoc packet')
        packet_proofs.append((packet, member, observation))
        artifacts.append({'kind': 'pandadoc', 'member_id': member['member_id'],
                          'remote_id': remote_id, 'url': url, 'verification': 'worker_observed',
                          'observed_at': datetime.fromtimestamp(observation['created'], timezone.utc).isoformat(),
                          'evidence': {'observation_id': observation['id'], 'recipient_email': member['member_email']}})

    folder = args['folder']
    folder_id, folder_url = _text(folder['remote_id']), _remote_url(folder['url'], 'storage')
    folder_observation = _observation(store, job, folder['observation_id'], [folder_url, folder_id], 'OneDrive folder')
    uploaded = []
    for file in files:
        doc = expected[(file['member_id'], file['document_type'], file['tax_year'])]
        file_id = _text(file['remote_file_id'])
        observation = _observation(store, job, file['observation_id'],
                                   [folder_id, file_id, doc.file.name, len(doc.file.data)], 'OneDrive file')
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
            'reservation_key': keys['pandadoc'][member['member_id']],
            'reservation_operation': CLOSEOUT_OPERATIONS['pandadoc'],
            'observation_id': observation['id'], 'case_key': claim['closeout']['closeout_form_id'],
            'coverage': 'Worker-observed packet and recipient; portal verification still required.'}, True)['id'])
    storage = wf.evidence(job, 'remote_record', folder_id, {
        'system': 'storage', 'remote_id': folder_id, 'url': folder_url,
        'external_key': folder['external_key'], 'reservation_key': keys['storage']['folder'],
        'reservation_operation': CLOSEOUT_OPERATIONS['storage'],
        'observation_id': folder_observation['id'],
        'case_key': claim['closeout']['closeout_form_id'], 'uploaded': uploaded,
        'coverage': 'Worker-observed Chrome records; not independent OneDrive API verification.'}, True)
    proof = wf.evidence(job, 'portal_delivery', identity.job_id, {
        'attempt_no': identity.attempt_no, 'fence_token': identity.fence_token,
        'document_evidence_ids': args['document_evidence_ids'], 'artifacts': artifacts}, True)
    # Only reservations under a canonical (system, operation, key) triple are confirmed by this delivery's own proofs.
    delivered = {('pandadoc', CLOSEOUT_OPERATIONS['pandadoc'], keys['pandadoc'][member['member_id']]): eid
                 for (_, member, _), eid in zip(packet_proofs, signing)}
    delivered[('storage', CLOSEOUT_OPERATIONS['storage'], keys['storage']['folder'])] = storage['id']
    ops, reconciled, unresolved = Operations(store), [], []
    for op in store.rows("SELECT id,system,operation,external_key FROM operations WHERE scope_key=? AND state='uncertain' ORDER BY created",
                         (job_scope(store, job),)):
        eid = delivered.get((op['system'], op['operation'], op['external_key']))
        try:
            if eid:
                ops.reconcile(job, op['id'], eid, auto='record_portal_delivery')
        except ValueError:
            eid = None  # The delivery proofs stand; the reservation stays uncertain for the model to inspect.
        (reconciled if eid else unresolved).append(op['id'])
    leftover = (' Uncertain reservations remain (' + ', '.join(unresolved) +
                '): inspect their remote state before finishing.') if unresolved else ''
    return {'delivery_evidence_id': proof['id'], 'signature_evidence_ids': signing,
            'storage_evidence_id': storage['id'],
            'reconciled_operation_ids': reconciled, 'unresolved_operation_ids': unresolved,
            'next': 'Reservations under the canonical triples are reconciled; save the remaining checkpoints.'
                    + leftover + ' The staff member who assigned this closeout to Clara receives it in Ready to Email for review.'}
