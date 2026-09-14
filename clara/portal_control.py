"""Relay questions and apply portal controls without replaying local actions."""
from dataclasses import asdict
from datetime import datetime
import json

from .portal_contract import ContractViolation
from .portal_lease import LeaseLost
from .portal_transport import PortalRejected, PortalUnavailable


class PortalControl:
    def __init__(self, store, manager, transport, journal, lease, local_job_id):
        self.store, self.manager, self.transport = store, manager, transport
        self.journal, self.lease, self.local_job_id = journal, lease, local_job_id
        self.identity = lease.identity
        row = store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (local_job_id,))
        if (journal.namespace != transport.base_url or not row or row['namespace'] != journal.namespace
                or (row['external_job_id'], row['worker_id'], row['attempt_no'], row['fence_token']) != (
                    self.identity.job_id, self.identity.worker_id, self.identity.attempt_no, self.identity.fence_token)):
            raise ContractViolation('This control channel does not own the local task.')

    async def heartbeat(self, stage=None):
        self.lease.assert_active()
        reply = await self._request('clara-heartbeat',
            {**asdict(self.identity), 'busy': True, 'stage': stage})
        body = reply.body
        if body['stop_requested'] or body.get('state') in {
                'stopping', 'stopped', 'cancelled', 'recovery_required', 'failed'}:
            self.lease.fence('The portal requested this task to stop.')
            await self.manager.cancel(self.local_job_id)
            raise LeaseLost(self.lease.reason)
        if not body.get('lease_expires_at'):
            self.lease.fence('The portal did not renew execution permission.')
            await self.manager.cancel(self.local_job_id)
            raise LeaseLost(self.lease.reason)
        self.lease.acknowledge(self.identity,
            expires_at=datetime.fromisoformat(body['lease_expires_at'].replace('Z', '+00:00')),
            server_time=datetime.fromisoformat(body['server_time'].replace('Z', '+00:00')),
            request_started=reply.request_started)
        return body['heartbeat_interval_s']

    async def _request(self, operation, body):
        try:
            return await self.transport.request(operation, body)
        except PortalRejected as error:
            if error.code in {'unauthorized', 'forbidden', 'fenced', 'lease_expired', 'execution_disabled'}:
                self.lease.fence('The portal withdrew execution permission.')
                await self.manager.cancel(self.local_job_id)
            raise

    async def publish_questions(self):
        self.lease.assert_active()
        for rid, item in list(self.manager.pending.items()):
            if item['job_id'] != self.local_job_id or item['future'].done():
                continue
            data = item['data']
            if item['kind'] == 'approval':
                body = {'question': 'Allow this action?', 'explanation': data.get('tool'),
                        'answer_type': 'choice', 'choices': ['Allow', 'Deny'],
                        'details': json.dumps(data.get('input', {}), ensure_ascii=False)}
            else:
                choices = [c['label'] for c in data.get('choices', [])]
                if len(set(choices)) != len(choices):
                    raise ContractViolation('Question choices need distinct labels.')
                body = {'question': data['question'], 'explanation': data.get('context'),
                        'answer_type': 'choice' if choices else 'text', 'choices': choices,
                        'details': data.get('details')}
            await self.transport.report(self.journal, self.identity, 'clara-ask', 'question-' + rid,
                {**asdict(self.identity), **body, 'request_id': rid, 'blocking': True})

    async def poll_commands(self):
        # Request all outstanding controls. Advancing a cursor must never hide a
        # Stop whose earlier acknowledgement was lost.
        reply = await self._request('clara-commands',
            {**asdict(self.identity), 'after_command_id': None})
        commands = reply.body['commands']
        ids = [c['command_id'] for c in commands]
        if len(ids) != len(set(ids)):
            raise ContractViolation('The portal repeated a command identity in the same response.')
        ordered = sorted(commands, key=lambda c: (c['type'] not in {'stop', 'cancel'}, c['command_id']))
        # Fence before any network acknowledgement or answer can yield to the model.
        if any(c['type'] in {'stop', 'cancel'} for c in ordered):
            self.lease.fence('The portal requested this task to stop.')
            await self.manager.cancel(self.local_job_id)
        for command in ordered:
            await self._command(command)

    async def _command(self, command):
        identity = self.identity
        key = (self.journal.namespace, identity.job_id, identity.attempt_no, command['command_id'])
        encoded = json.dumps(command, sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT * FROM portal_v1_commands WHERE namespace=?
                AND external_job_id=? AND attempt_no=? AND command_id=?''', key).fetchone()
            if row:
                if (row['worker_id'], row['fence_token'], row['request_json']) != (
                        identity.worker_id, identity.fence_token, encoded):
                    raise ContractViolation('A command identity was reused with different content.')
                if row['state'] != 'applied':
                    raise PortalUnavailable('A previous local command outcome needs review before continuing.')
                status = row['status']
            else:
                db.execute('''INSERT INTO portal_v1_commands VALUES(?,?,?,?,?,?,?,'processing',NULL)''',
                    (self.journal.namespace, identity.job_id, identity.worker_id,
                     identity.attempt_no, identity.fence_token, command['command_id'], encoded))
                status = None
        if status is None:
            status = 'expired'
            if command['type'] in {'stop', 'cancel'}:
                # poll_commands already fenced and cancelled before any answer.
                status = 'accepted'
            elif command['type'] == 'continue':
                # Its messages remain in the portal's pending continuation.
                # Receipt of this signal never injects a second model execution.
                status = 'accepted'
            else:
                item = self.manager.pending.get(command['request_id'])
                if item and item['job_id'] == self.local_job_id and not item['future'].done():
                    try:
                        self.lease.assert_active()
                        value = command['value']
                        if item['kind'] == 'approval':
                            value = {'Allow': 'allow', 'Deny': 'deny'}.get(value, value)
                        else:
                            matches = [c['answer'] for c in item['data'].get('choices', []) if c['label'] == value]
                            if len(matches) == 1:
                                value = matches[0]
                        self.manager.answer(command['request_id'], value)
                        status = 'accepted'
                    except (LeaseLost, ValueError):
                        status = 'expired'
            self.store.execute('''UPDATE portal_v1_commands SET state='applied',status=?
                WHERE namespace=? AND external_job_id=? AND attempt_no=? AND command_id=?''', (status, *key))
        await self.transport.report(self.journal, identity, 'clara-command-ack',
            'command-' + str(command['command_id']),
            {**asdict(identity), 'command_id': command['command_id'], 'status': status,
             'checkpoint': None, 'note': None})
