"""Relay scoped chat and concise activity with durable, repeatable event IDs."""
from dataclasses import asdict
import re
from datetime import datetime, timezone
import json

from .portal_contract import ContractViolation


def check_binding(store, namespace, identity, local_job_id):
    row = store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (local_job_id,))
    if (not row or row['namespace'] != namespace or
            (row['external_job_id'], row['worker_id'], row['attempt_no'], row['fence_token']) !=
            (identity.job_id, identity.worker_id, identity.attempt_no, identity.fence_token)):
        raise ContractViolation('This report does not belong to the local portal attempt.')
    return row


# The portal shows "what Clara is doing" from these fields alone. An application
# label comes from a fixed allowlist; the tool's input is only searched for
# those names and is never forwarded, so window titles, file paths, command
# text and client data stay on the worker.
APP_HINTS = ((r'\bt1txp\b|\btaxprep\b', 'TaxPrep'), (r'\bpandadoc\b', 'PandaDoc'),
             (r'\bsharepoint\b|\bonedrive\b|\b1drv\b', 'OneDrive'), (r'\bacrord32\b|\bacrobat\b', 'Acrobat'),
             (r'\bwinword\b', 'Word'), (r'\bexcel\.exe\b|\bmicrosoft excel\b', 'Excel'),
             (r'\bmsedge\b|\bmicrosoft edge\b', 'Edge'), (r'\bchrome\b', 'Chrome'),
             (r'\bprofile\.exe\b|\bintuit profile\b', 'ProFile'), (r'\bexplorer\.exe\b|\bfile explorer\b', 'Explorer'))


def tool_surface(name):
    """desktop for the Windows bridge, browser for Chrome, worker for Clara's own tools."""
    if name.startswith('mcp__windows__'):
        return 'desktop'
    if name.startswith('mcp__chrome__'):
        return 'browser'
    return 'worker'


def app_hint(name, raw_input):
    """An allowlisted application name for the action, or None.

    Program and site names are matched as whole words (or executable names), so
    ordinary typed text such as "client profile" or "excellent" never becomes a
    label; a browser page is labelled by its site, otherwise by the browser.
    """
    text = (raw_input if isinstance(raw_input, str) else '').casefold()[:4000]
    if name.startswith('mcp__chrome__'):
        for pattern, label in APP_HINTS:
            if label in {'PandaDoc', 'OneDrive'} and re.search(pattern, text):
                return label
        return 'Chrome'
    if name.startswith('mcp__windows__'):
        for pattern, label in APP_HINTS:
            if re.search(pattern, text):
                return label
    return None


class PortalProgress:
    def __init__(self, store, transport, journal, lease, local_job_id):
        self.store, self.transport, self.journal = store, transport, journal
        self.lease, self.local_job_id = lease, local_job_id
        if journal.namespace != transport.base_url:
            raise ContractViolation('This report belongs to another portal.')
        check_binding(store, journal.namespace, lease.identity, local_job_id)

    async def flush(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Choose a progress batch of 1–500 local events.')
        self.lease.assert_active()
        row = self.store.one('SELECT event_id FROM portal_v1_progress WHERE namespace=? AND local_job_id=?',
                             (self.journal.namespace, self.local_job_id))
        after = row['event_id'] if row else 0
        events = self.store.rows('SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id LIMIT ?',
                                 (self.local_job_id, after, limit))
        for event in events:
            self.lease.assert_active()
            data = json.loads(event['data'])
            uid = 'local-' + str(event['id'])
            if event['kind'] == 'assistant' and data.get('text', '').strip():
                # Split without dropping context; a replay keeps each chunk's
                # original identity. Streaming deltas are not sent a second time.
                body = data['text']
                for index, offset in enumerate(range(0, len(body), 16000)):
                    self.lease.assert_active()
                    part = uid + '-' + str(index)
                    await self.transport.report(self.journal, self.lease.identity,
                        'clara-chat', part, {**asdict(self.lease.identity),
                            'message_uid': part, 'body': body[offset:offset+16000], 'final': False})
            elif event['kind'] in {'tool', 'tool_done', 'status', 'checkpoint'}:
                level, stage, message, meta = self._activity(event['kind'], data)
                await self.transport.report(self.journal, self.lease.identity,
                    'clara-events', uid, {**asdict(self.lease.identity), 'events': [{
                        'event_uid': uid, 'level': level, 'stage': stage, 'message': message, 'meta': meta,
                        'at': datetime.fromtimestamp(event['created'], timezone.utc).isoformat()}]})
            # Only acknowledged events (or deliberately local-only diagnostics)
            # advance this cursor. A crash between receipt and cursor repeats a
            # journal lookup, never another logical chat message.
            self.store.execute('''INSERT INTO portal_v1_progress VALUES(?,?,?)
                ON CONFLICT(namespace,local_job_id) DO UPDATE SET event_id=max(event_id,excluded.event_id)''',
                (self.journal.namespace, self.local_job_id, event['id']))
        return len(events)

    @staticmethod
    def _activity(kind, data):
        """(level, stage, message, meta) for the portal; never command input/output, login data or signed URLs."""
        if kind in {'tool', 'tool_done'}:
            full = str(data.get('name', 'Action'))
            name = full.rsplit('__', 1)[-1][:100]
            meta = {'kind': kind, 'tool': name, 'surface': tool_surface(full), 'app': app_hint(full, data.get('input'))}
            if kind == 'tool':
                return 'info', 'working', 'Using ' + name + '.', meta
            failed = data.get('failed') is True
            return ('warn' if failed else 'info'), 'working', name + (' reported a problem.' if failed else ' returned.'), meta
        if kind == 'checkpoint':
            # The stage name and status let the portal show honest progress chips.
            stage = str(data.get('stage', ''))[:64]
            status = str(data.get('status', ''))[:32]
            if stage and status:
                return 'info', 'checkpoint', f'Saved workflow progress: {stage} {status}.', {'stage': stage, 'status': status}
            return 'info', 'checkpoint', 'Saved workflow progress.', None
        status = data.get('status')
        messages = {'queued': 'Queued for this computer.', 'running': 'Clara is working.',
                    'waiting': 'Waiting for your answer.', 'cancelling': 'Stopping current work.',
                    'cancelled': 'Execution stopped. Review existing work before continuing.',
                    'interrupted': 'Execution was interrupted. Existing work needs review.',
                    'failed': 'Clara could not finish this task. Review the task details.',
                    'incomplete': 'Some workflow steps remain unfinished.',
                    'needs_review': 'The task needs review.',
                    'completed': 'Local execution finished. Portal verification follows.'}
        return ('warn' if status in {'failed', 'interrupted', 'incomplete'} else 'info'), 'execution', messages.get(status, 'Task state changed.'), None
