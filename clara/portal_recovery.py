"""Explicitly finish a saved T1 portal report, with no model or desktop work."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from uuid import UUID

from .auth import portal_credential
from .config import Config, default_data
from .instance import single_instance
from .portal import PortalWorker
from .portal_journal import PortalJournal
from .portal_lease import AttemptIdentity
from .portal_results import PortalResults
from .portal_transport import PortalTransport, PortalRejected, PortalUnavailable
from .store import Store


def saved_attempt(store, namespace, identity):
    if store.one("SELECT id FROM jobs WHERE status IN ('queued','running','waiting','cancelling') LIMIT 1"):
        raise ValueError('A local task is still active. Let it settle before recovering the portal report.')
    rows = store.rows('''SELECT * FROM portal_v1_cycles WHERE namespace=? AND worker_id=?
        AND finished IS NULL''', (namespace, identity.worker_id))
    if len(rows) != 1 or not rows[0]['claim_json']:
        raise ValueError('Exactly one saved worker hold is required for this recovery.')
    cycle = rows[0]
    claim = json.loads(cycle['claim_json'])
    if any(claim.get(k) != v for k, v in asdict(identity).items() if k != 'worker_id'):
        raise ValueError('This worker hold belongs to another job or attempt.')
    binding = store.one('''SELECT * FROM portal_v1_attempts WHERE namespace=? AND external_job_id=?
        AND worker_id=? AND attempt_no=? AND fence_token=?''',
        (namespace, identity.job_id, identity.worker_id, identity.attempt_no, identity.fence_token))
    if not binding or binding['local_job_id'] != cycle['local_job_id']:
        raise ValueError('The saved execution binding does not match the worker hold.')
    job = store.job(binding['local_job_id'])
    if not job or job['status'] not in {'completed', 'needs_review'} or not job['finished']:
        raise ValueError('The original local task must have finished successfully before report recovery.')
    return job['id']


async def recover(config, args):
    settings = PortalWorker(config, None, None).settings()
    if not settings or settings.get('protocol_version') != 1:
        raise ValueError('The existing portal connection must be configured first.')
    identity = AttemptIdentity(str(UUID(args.job_id)), settings['worker_id'], args.attempt, args.fence)
    store = Store(config.data / 'clara.sqlite3')
    jid = saved_attempt(store, settings['base_url'], identity)
    transport = PortalTransport(settings['base_url'], lambda: portal_credential(settings['token_env']))
    reporter = PortalResults(config, store, transport, PortalJournal(store, settings['base_url']))
    try:
        if not args.send:
            payload = reporter.saved_closeout_payload(identity, jid)
            folder = next(a for a in payload['artifacts'] if a['kind'] == 'onedrive_folder')
            print(json.dumps({**asdict(identity), 'check': 'ready_to_report',
                'local_status': store.job(jid)['status'], 'pdf_uploads_to_portal': 0,
                'packets': len(payload['artifacts']) - 1,
                'onedrive_files': len(folder['evidence']['uploaded']),
                'usage': payload['usage'], 'network_requests': 0}, indent=2))
            return
        receipt = await reporter.report_saved_closeout(identity, jid)
        print(json.dumps({'result_recorded': receipt['result_recorded'],
            'receipt_id': receipt['receipt_id'], 'handoff': receipt['handoff'],
            'job_state': receipt['job_state'],
            'next': 'Start Clara normally to report desktop quiescence. No task was restarted.'}, indent=2))
    finally:
        await reporter.close()
        await transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=default_data())
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--attempt', required=True, type=int)
    parser.add_argument('--fence', required=True, type=int)
    parser.add_argument('--send', action='store_true', help='Submit the existing result under portal authorization.')
    args = parser.parse_args()
    if args.attempt < 1 or args.fence < 1:
        parser.error('Attempt and fence must be positive.')
    config = Config(args.data_dir.expanduser().resolve())
    if not (config.data / 'clara.sqlite3').is_file():
        parser.error('Use the existing Clara data folder.')
    try:
        # Neither the service nor another recovery command can run concurrently.
        with single_instance(config.data):
            asyncio.run(recover(config, args))
    except (ValueError, RuntimeError, OSError) as error:
        if isinstance(error, PortalRejected):
            message = str(error)  # Structured code/status only, no provider body.
        elif isinstance(error, PortalUnavailable):
            message = 'The portal receipt is unavailable. Preserve the saved report and retry this same command.'
        else:
            message = 'Recovery checks did not pass. Keep the existing results and worker hold for review.'
        raise SystemExit(message) from None


if __name__ == '__main__':
    main()
