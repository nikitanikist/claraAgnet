"""Persist outbound portal reports before sending them.

Pending rows authorize retrying a report with its original identity and payload;
they never authorize restarting a model task or replaying a desktop action.
Credentials, signed URLs and file bytes belong in the transport, not this journal.
"""
from dataclasses import asdict
import hashlib
import json
import time

from .portal_lease import AttemptIdentity


class JournalConflict(ValueError):
    """A durable idempotency key or receipt was reused with different data."""


def _encode(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False)
    if len(encoded.encode('utf-8')) > 1_048_576:
        raise ValueError('Portal report exceeds the local journal limit.')
    return encoded


class PortalJournal:
    def __init__(self, store, namespace):
        # The caller binds this to the configured portal origin/project. Different
        # portals must not share receipts, even if their job UUIDs happen to match.
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 500:
            raise ValueError('A portal journal needs a stable portal namespace.')
        self.store = store
        self.namespace = namespace

    def stage(self, identity, operation, request_key, payload):
        if not isinstance(identity, AttemptIdentity):
            raise ValueError('A report requires an exact attempt identity.')
        if any(not isinstance(v, str) or not v.strip() or len(v) > limit
               for v, limit in ((operation, 80), (request_key, 200))):
            raise ValueError('A report needs an operation and an idempotency key.')
        if not isinstance(payload, dict):
            raise ValueError('A report payload must be an object.')
        # Attempt identity cannot drift between the durable row and the wire body.
        for key, value in asdict(identity).items():
            if type(payload.get(key)) is not type(value) or payload.get(key) != value:
                raise JournalConflict('Report payload belongs to a different attempt.')
        encoded = _encode(payload)
        digest = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        args = (self.namespace, identity.job_id, identity.worker_id,
                identity.attempt_no, identity.fence_token, operation, request_key)
        with self.store.connect() as db:
            # Serializes duplicate concurrent stage calls before the uniqueness
            # check. The same logical retry returns the existing immutable row.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT * FROM portal_v1_outbox WHERE
                namespace=? AND external_job_id=? AND worker_id=? AND attempt_no=?
                AND fence_token=? AND operation=? AND request_key=?''', args).fetchone()
            if row:
                if row['request_hash'] != digest:
                    raise JournalConflict('A portal report key was reused with different content.')
                return self._decode(row)
            cursor = db.execute('''INSERT INTO portal_v1_outbox
                (namespace,external_job_id,worker_id,attempt_no,fence_token,
                 operation,request_key,request_hash,payload,created)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (*args, digest, encoded, time.time()))
            row = db.execute('SELECT * FROM portal_v1_outbox WHERE id=?',
                             (cursor.lastrowid,)).fetchone()
            return self._decode(row)

    def acknowledge(self, report_id, response):
        """Call only after the transport validates a matching server receipt."""
        if not isinstance(response, dict):
            raise ValueError('A portal receipt must be an object.')
        encoded = _encode(response)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM portal_v1_outbox WHERE id=? AND namespace=?',
                             (report_id, self.namespace)).fetchone()
            if not row:
                raise JournalConflict('Unknown report in this portal journal.')
            if row['receipt'] is not None:
                if row['receipt'] != encoded:
                    raise JournalConflict('The stored portal receipt cannot be replaced.')
                return self._decode(row)
            db.execute('UPDATE portal_v1_outbox SET receipt=?,acknowledged=? WHERE id=?',
                       (encoded, time.time(), report_id))
            return self._decode(db.execute('SELECT * FROM portal_v1_outbox WHERE id=?',
                                           (report_id,)).fetchone())

    def pending(self, identity=None, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Report batch size must be between 1 and 1000.')
        sql = 'SELECT * FROM portal_v1_outbox WHERE namespace=? AND acknowledged IS NULL'
        args = [self.namespace]
        if identity is not None:
            if not isinstance(identity, AttemptIdentity):
                raise ValueError('Filter reports by an exact attempt identity.')
            sql += ' AND external_job_id=? AND worker_id=? AND attempt_no=? AND fence_token=?'
            args.extend((identity.job_id, identity.worker_id, identity.attempt_no, identity.fence_token))
        sql += ' ORDER BY id LIMIT ?'
        args.append(limit)
        return [self._decode(row) for row in self.store.rows(sql, args)]

    @staticmethod
    def _decode(row):
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        if result['receipt'] is not None:
            result['receipt'] = json.loads(result['receipt'])
        return result
