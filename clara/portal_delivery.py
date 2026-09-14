"""Receive a frozen message window durably before acknowledging its delivery.

Reading or acknowledging a window never starts a model. A restart may repeat
these idempotent steps, but must not replay an already dispatched local job.
"""
from dataclasses import asdict
import json

from .portal_contract import ContractViolation
from .portal_transport import PortalUnavailable


class PortalDelivery:
    def __init__(self, store, transport):
        self.store, self.transport = store, transport
        self.namespace = transport.base_url

    def _existing(self, identity):
        row = self.store.one('''SELECT * FROM portal_v1_deliveries
            WHERE namespace=? AND external_job_id=? AND attempt_no=?''',
            (self.namespace, identity.job_id, identity.attempt_no))
        if row and (row['worker_id'] != identity.worker_id or row['fence_token'] != identity.fence_token):
            raise ContractViolation('The saved message window belongs to a different execution.')
        return row

    async def receive(self, claim, lease):
        self.transport.contract.validate('clara-claim', 'response', claim)
        identity = lease.identity
        if (claim.get('claimed') is not True or claim['job_id'] != identity.job_id
                or claim['attempt_no'] != identity.attempt_no or claim['fence_token'] != identity.fence_token):
            raise ContractViolation('The message window belongs to a different execution.')
        lease.assert_active()
        start, end = claim['delivery_from_seq'], claim['message_boundary_seq']
        if start > end and (start, end) != (1, 0):
            raise ContractViolation('The portal returned an invalid task message range.')
        existing = self._existing(identity)
        if existing:
            if (existing['from_seq'], existing['to_seq']) != (start, end):
                raise ContractViolation('The portal changed an already received message boundary.')
            return json.loads(existing['messages_json'])

        # Page from the frozen range independently of the short page embedded in
        # the claim. Global sequence numbers can have gaps between conversations.
        after, messages, message_ids = start - 1, [], set()
        total_bytes = 0
        while after < end:
            lease.assert_active()
            reply = await self.transport.request('clara-messages',
                {**asdict(identity), 'after_seq': after, 'limit': 100})
            lease.assert_active()
            page = reply.body
            if (page['from_seq'], page['to_seq']) != (start, end):
                raise ContractViolation('The portal changed the claimed message window.')
            rows = page['messages']
            if not rows:
                raise PortalUnavailable('The portal did not deliver the complete claimed message window.')
            for message in rows:
                seq, mid = message['seq'], message['message_id']
                if not after < seq <= end or mid in message_ids:
                    raise ContractViolation('The portal returned repeated or out-of-order task messages.')
                after = seq
                message_ids.add(mid)
                messages.append(message)
                total_bytes += len(json.dumps(message, ensure_ascii=False).encode())
                if len(messages) > 10000 or total_bytes > 2_000_000:
                    raise PortalUnavailable('This message window needs review before desktop work can start.')
            if page['more_messages'] is not (after < end):
                raise ContractViolation('The portal reported an inconsistent message boundary.')
        encoded = json.dumps(messages, sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''INSERT OR IGNORE INTO portal_v1_deliveries
                VALUES(?,?,?,?,?,?,?,?,0)''', (self.namespace, identity.job_id,
                identity.worker_id, identity.attempt_no, identity.fence_token, start, end, encoded))
            saved = db.execute('''SELECT * FROM portal_v1_deliveries
                WHERE namespace=? AND external_job_id=? AND attempt_no=?''',
                (self.namespace, identity.job_id, identity.attempt_no)).fetchone()
            if (saved['worker_id'], saved['fence_token'], saved['from_seq'], saved['to_seq'], saved['messages_json']) != (
                    identity.worker_id, identity.fence_token, start, end, encoded):
                raise ContractViolation('The same message delivery was reused with different content.')
        return messages

    async def acknowledge(self, lease):
        identity = lease.identity
        lease.assert_active()
        row = self._existing(identity)
        binding = self.store.one('''SELECT * FROM portal_v1_attempts
            WHERE namespace=? AND external_job_id=? AND attempt_no=?''',
            (self.namespace, identity.job_id, identity.attempt_no))
        if (not row or not binding or binding['worker_id'] != identity.worker_id
                or binding['fence_token'] != identity.fence_token):
            raise ContractViolation('Save the complete task and its local binding before acknowledging delivery.')
        if row['acknowledged']:
            return
        reply = await self.transport.request('clara-message-ack',
            {**asdict(identity), 'acked_seq': row['to_seq']})
        lease.assert_active()
        body = reply.body
        if body['complete'] is not True or body['acked_seq'] != row['to_seq'] or body['to_seq'] != row['to_seq']:
            raise PortalUnavailable('The portal has not acknowledged the complete task window.')
        self.store.execute('''UPDATE portal_v1_deliveries SET acknowledged=1
            WHERE namespace=? AND external_job_id=? AND attempt_no=? AND worker_id=? AND fence_token=?''',
            (self.namespace, identity.job_id, identity.attempt_no, identity.worker_id, identity.fence_token))
