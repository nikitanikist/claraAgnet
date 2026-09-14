"""Describe observed local activity; absence of a reply is never success."""
from datetime import datetime, timezone
import json

from .knowledge import job_scope
from .portal_progress import check_binding


def observe_quiescence(store, manager, namespace, identity, local_job_id):
    check_binding(store, namespace, identity, local_job_id)
    job = store.job(local_job_id)
    finished, running, unknown = set(), set(), set()
    busy = bool(manager.active_job or not manager.queue.empty() or
                any(not item['future'].done() for item in manager.pending.values()))
    if busy:
        running.add('local-executor')
    if job['status'] in {'queued', 'running', 'waiting', 'cancelling'} and not busy:
        unknown.add('local-task-state')
    started, returned = set(), set()
    external_actions = False
    after = 0
    while True:
        events = store.rows("SELECT id,kind,data FROM events WHERE job_id=? AND id>? AND kind IN ('tool','tool_done') ORDER BY id LIMIT 500",
                            (local_job_id, after))
        if not events:
            break
        for event in events:
            after = event['id']
            data = json.loads(event['data'])
            if not isinstance(data.get('id'), str) or not data['id']:
                unknown.add('unidentified-tool-call')
                continue
            ref = 'tool:' + data['id']
            if event['kind'] == 'tool':
                started.add(ref)
                name = str(data.get('name', ''))
                leaf = name.rsplit('__', 1)[-1]
                readonly = leaf in {'Snapshot', 'Screenshot', 'ListWindows', 'InspectControls',
                                   'ApplicationInfo', 'VerifyWindow', 'take_snapshot',
                                   'take_screenshot', 'list_pages'}
                if name in {'Bash', 'PowerShell'} or (name.startswith(('mcp__windows__', 'mcp__chrome__')) and not readonly):
                    external_actions = True
            else:
                returned.add(ref)
        if len(events) < 500:
            break
    # A tool's return only confirms that the local call returned. Reserved
    # external writes separately require their verified remote reconciliation.
    finished.update(returned)
    (running if busy else unknown).update(started - returned)
    if external_actions:
        # A completed click or shell call cannot prove a print, upload, or
        # detached process stopped. The future Windows observer/recovery flow
        # must settle this reference using fresh external state before release.
        unknown.add('external-desktop-state-unconfirmed')
    operations = store.rows('SELECT id,state FROM operations WHERE scope_key=?', (job_scope(store, job),))
    for op in operations:
        ref = 'operation:' + op['id']
        (unknown if op['state'] == 'uncertain' else finished).add(ref)
    uploads = store.rows('''SELECT file_id,state FROM portal_v1_uploads WHERE namespace=? AND
        external_job_id=? AND worker_id=? AND attempt_no=? AND fence_token=?''',
        (namespace, identity.job_id, identity.worker_id, identity.attempt_no, identity.fence_token))
    for upload in uploads:
        ref = 'attachment:' + upload['file_id']
        (finished if upload['state'] == 'uploaded' else unknown).add(ref)
    # Never silently truncate unresolved references: the portal must reconcile
    # every unknown action, not just the first page. This stops release until a
    # larger report protocol or explicit local review is available.
    if len(running) > 200 or len(unknown) > 200 or any(len(v) > 200 for v in running | unknown):
        raise ValueError('This recovery report exceeds the portal limit; retain the worker hold for review.')
    return {'finished': sorted(v for v in finished if len(v) <= 200)[-200:],
            'in_flight': sorted(running), 'unknown': sorted(unknown),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'complete': not running and not unknown}
