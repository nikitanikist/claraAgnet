"""Operator-reviewed release of a finished T1 worker; never resumes its task."""
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time
from uuid import UUID

from .config import Config, default_data
from .auth import portal_credential
from .instance import single_instance
from .knowledge import job_scope
from .portal import PortalWorker
from .portal_journal import PortalJournal
from .portal_lease import AttemptIdentity
from .portal_quiescence import observe_quiescence
from .portal_recovery import saved_attempt
from .portal_transport import PortalTransport, PortalRejected, PortalUnavailable
from .portal_windows import native_snapshot, validate_snapshot
from .store import Store


def reviewed_operations(store, namespace, identity, jid, mappings):
    """An operator may bind a different display title to the reserved business key.

    The original key and evidence stay unchanged. Every mapping must point to
    verified evidence for a packet, or for the one OneDrive folder, in the
    acknowledged delivery of this attempt. A storage reservation may only be
    bound to that delivered folder; PandaDoc reservations only to its packets.
    """
    row = store.one('''SELECT payload,receipt FROM portal_v1_outbox WHERE namespace=?
        AND external_job_id=? AND worker_id=? AND attempt_no=? AND fence_token=?
        AND operation='clara-result' AND request_key=? AND acknowledged IS NOT NULL''',
        (namespace, identity.job_id, identity.worker_id, identity.attempt_no,
         identity.fence_token, 'result-' + jid))
    if not row:
        raise ValueError('An acknowledged finished closeout result is required.')
    payload, receipt = json.loads(row['payload']), json.loads(row['receipt'])
    if (payload.get('outcome') != 'completed_prepared' or
            receipt.get('job_state') != 'completed_prepared' or
            receipt.get('handoff', {}).get('status') != 'ready_to_email'):
        raise ValueError('The portal has not confirmed Ready to Email.')
    packets = {a['remote_id'] for a in payload['artifacts'] if a['kind'] == 'pandadoc'}
    folders = {a['remote_id'] for a in payload['artifacts'] if a['kind'] == 'onedrive_folder'}
    job = store.job(jid)
    operations = store.rows("SELECT * FROM operations WHERE scope_key=? AND state='uncertain'",
                            (job_scope(store, job),))
    if set(mappings) != {op['id'] for op in operations}:
        raise ValueError('Review every uncertain operation exactly once.')
    resolved = []
    for op in operations:
        evidence = store.one('SELECT * FROM evidence WHERE id=? AND job_id=? AND kind=? AND verified=1',
                             (mappings[op['id']], jid, 'remote_record'))
        proof = json.loads(evidence['payload']) if evidence else {}
        if op['system'] == 'pandadoc':
            matches = (op['operation'] == 'create_signature_packet'
                       and proof.get('system') == 'pandadoc' and proof.get('remote_id') in packets)
        elif op['system'] == 'storage':
            matches = proof.get('system') == 'storage' and proof.get('remote_id') in folders
        else:
            matches = False
        if not evidence or not matches or evidence['created'] < op['updated']:
            raise ValueError('The reviewed packet or folder evidence does not match the saved delivery.')
        resolved.append({'operation_id': op['id'], 'evidence_id': evidence['id'],
                         'remote_id': proof['remote_id'], 'reserved_key': op['external_key'],
                         'observed_key': proof.get('external_key')})
    if len({r['remote_id'] for r in resolved}) != len(resolved):
        raise ValueError('Different reservations must not be mapped to the same packet or folder.')
    return resolved


def check_desktop(snapshot):
    validate_snapshot(snapshot)
    if snapshot['print_jobs']:
        raise ValueError('Settle printing before review.')
    # A stopped service must not leave a model/browser/controller running. A
    # name is only a blocker here; it never authorizes terminating a process.
    executors = {'claude.exe', 'node.exe', 'python.exe', 'pythonw.exe',
                 'chrome.exe', 'msedge.exe', 't1txp.exe', 'profile.exe',
                 'winword.exe', 'excel.exe', 'acrord32.exe', 'acrobat.exe'}
    if any(p.get('name', '').casefold() in executors and p['pid'] not in snapshot['ancestors']
           for p in snapshot['processes']):
        raise ValueError('A separate model or controller process still needs review.')


async def release(config, identity, mappings, note, *, probe=native_snapshot, pause=asyncio.sleep):
    settings = PortalWorker(config, None, None).settings()
    if (not settings or settings.get('protocol_version') != 1 or
            settings['worker_id'] != identity.worker_id or
            settings.get('windows_handoff', {}).get('exclusive_session') is not True):
        raise ValueError('Use the configured dedicated worker.')
    if len(note.strip()) < 30:
        raise ValueError('Record the operator inspection and packet mapping rationale.')
    store = Store(config.data / 'clara.sqlite3')
    jid = saved_attempt(store, settings['base_url'], identity)
    cycle = store.one('SELECT * FROM portal_v1_cycles WHERE local_job_id=? AND finished IS NULL', (jid,))
    resolved = reviewed_operations(store, settings['base_url'], identity, jid, mappings)
    manager = SimpleNamespace(active_job=None, queue=asyncio.Queue(), pending={})
    original = observe_quiescence(store, manager, settings['base_url'], identity, jid)
    allowed = {'external-desktop-state-unconfirmed'} | {'operation:' + r['operation_id'] for r in resolved}
    if original['in_flight'] or set(original['unknown']) - allowed:
        raise ValueError('Unfinished tools, attachments or other actions still require review.')
    first = await probe()
    check_desktop(first)
    await pause(3)
    second = await probe()
    check_desktop(second)
    if (any(first[k] != second[k] for k in ('owner', 'session', 'controller')) or
            abs(first['boot'] - second['boot']) > 2):
        raise ValueError('The observed desktop changed; inspect it again.')
    # This is an explicit review of an acknowledged completed task. Both fresh
    # observations must have no task controllers/apps or pending printing.
    # Whole-session PID equality is not a readiness signal: Windows can create
    # and retire conhost processes for the observation itself. Unrelated chat
    # windows and background processes are retained in the audit, not blockers.
    # Save the actual old uncertainties and fresh inspection. This is an
    # explicit operator review, never automatic qualification of future tasks
    # and never a replacement of the original Windows baseline.
    review = {'identity': asdict(identity), 'local_job_id': jid, 'note': note,
              'original_report': original, 'operations': resolved,
              'observations': [first, second], 'reviewed_at': time.time()}
    encoded = json.dumps(review, sort_keys=True, allow_nan=False)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    folder = config.data / 'diagnostics'
    folder.mkdir(exist_ok=True)
    (folder / ('worker-release-review-' + digest + '.json')).write_text(encoded, encoding='utf-8')
    report = {'finished': ['operator-reviewed-completed-task:' + digest], 'in_flight': [], 'unknown': [],
              'observed_at': datetime.now(timezone.utc).isoformat(), 'complete': True}
    transport = PortalTransport(settings['base_url'], lambda: portal_credential(settings['token_env']))
    try:
        receipt = await transport.report(PortalJournal(store, settings['base_url']), identity,
            'clara-quiesce', 'operator-quiet-' + digest, {**asdict(identity), 'report': report})
        if receipt.get('quiescent') is not True or receipt.get('recovery_hold') is not False:
            raise ValueError('The portal retained its worker hold.')
        # Only a validated portal receipt releases the local slot. Keep the
        # cycle, operation reservations, original evidence and review as audit.
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in resolved:
                db.execute("UPDATE operations SET state='confirmed',remote_id=?,result=?,updated=? WHERE id=? AND state='uncertain'",
                    (row['remote_id'], json.dumps({'evidence_id': row['evidence_id'], 'operator_review': digest}),
                     time.time(), row['operation_id']))
                db.execute('INSERT INTO operation_audit(operation_id,action,note,created) VALUES(?,?,?,?)',
                    (row['operation_id'], 'operator_verified_existing_packet', encoded, time.time()))
            db.execute("UPDATE portal_v1_cycles SET state='reconciled',finished=?,error=NULL WHERE id=? AND finished IS NULL",
                       (time.time(), cycle['id']))
        return {'released': True, 'review': digest, 'result_preserved': True, 'task_restarted': False}
    finally:
        await transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=default_data())
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--worker-id', required=True)
    parser.add_argument('--attempt', type=int, required=True)
    parser.add_argument('--fence', type=int, required=True)
    parser.add_argument('--operation', action='append', default=[], help='Reviewed operation-id=evidence-id mapping')
    parser.add_argument('--note', required=True)
    parser.add_argument('--confirm-desktop-idle', action='store_true')
    args = parser.parse_args()
    if not args.confirm_desktop_idle or args.attempt < 1 or args.fence < 1:
        parser.error('Inspect the dedicated desktop first and explicitly confirm it is idle.')
    config = Config(args.data_dir.expanduser().resolve())
    if not (config.data / 'clara.sqlite3').is_file():
        parser.error('Use the existing Clara data folder.')
    try:
        pairs = [value.split('=') for value in args.operation]
        mappings = dict(pairs)
        if len(mappings) != len(pairs):
            raise ValueError('Duplicate operation mapping.')
        identity = AttemptIdentity(str(UUID(args.job_id)), str(UUID(args.worker_id)), args.attempt, args.fence)
        with single_instance(config.data):
            print(json.dumps(asyncio.run(release(config, identity, mappings, args.note)), indent=2))
    except (ValueError, RuntimeError, OSError) as error:
        if isinstance(error, PortalRejected):
            message = str(error)
        elif isinstance(error, PortalUnavailable):
            message = 'No release receipt; preserve the review and check portal state before retrying.'
        else:
            message = str(error)
        raise SystemExit(message) from None


if __name__ == '__main__':
    main()
