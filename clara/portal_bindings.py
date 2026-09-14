"""Bind an authenticated portal claim to private local history before enqueue.

Persisting a claim never enqueues it. Returning an existing binding is evidence
of previous work, not permission to run that work again after a crash.
"""
from dataclasses import asdict
import hashlib
import json
import time

from .portal_contract import ContractViolation, PortalContract
from .portal_lease import AttemptIdentity
from .store import new_id


class BindingConflict(ValueError):
    pass


class PortalBindings:
    def __init__(self, store, namespace, worker_id, *, contract=None):
        self.store, self.namespace, self.worker_id = store, namespace, worker_id
        self.contract = contract or PortalContract.bundled()

    def persist_claim(self, claim, prompt):
        """Caller has reserved the executor and authenticated this server response.

        The local adapter constructs the prompt from the claim's scoped data;
        neither a model nor a portal chat message can call this entrypoint.
        A later executor step must validate the live lease before enqueueing.
        """
        self.contract.validate('clara-claim', 'response', claim)
        if claim.get('claimed') is not True:
            raise ContractViolation('Only a complete positive claim can create local work.')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100_000:
            raise ValueError('The scoped portal task prompt is missing or too large.')
        try:
            identity = AttemptIdentity(claim['job_id'], self.worker_id,
                                       claim['attempt_no'], claim['fence_token'])
            cid, kind = claim['conversation_id'], claim['kind']
            owner = claim['scope']['assigned_by']
            execution_id = claim['execution_id']
            policy = claim['policy']
        except (KeyError, TypeError, ValueError):
            raise ContractViolation('The claimed task is missing its execution identity or scope.') from None
        if (policy.get('may_send_client_email') is not False or policy.get('may_efile') is not False
                or policy.get('may_sign') is not False or policy.get('stop_at') != 'ready_to_email'):
            raise ContractViolation('The portal policy does not match the supported preparation scope.')
        closeout_id = None
        if kind == 'closeout':
            closeout = claim.get('closeout') or {}
            closeout_id = closeout.get('closeout_form_id')
            if (not closeout_id or closeout.get('form_type') != 'Personal Tax'
                    or closeout.get('software') != 'taxprep'
                    or not closeout.get('members') or policy.get('invoice_mode') != 'laureen_manual'
                    or claim['scope'].get('closeout_form_id') != closeout_id
                    or 'closeout.t1.taxprep' not in claim['scope']['permissions']):
                raise ContractViolation('This worker supports authorized T1 TaxPrep preparation only.')
        elif kind != 'general':
            raise ContractViolation('This worker does not support the requested task kind.')

        # Server lease timing may change on a retried receipt, but the actual
        # assignment and its message boundary must not change within an attempt.
        stable_claim = {k: v for k, v in claim.items()
                        if k not in {'server_time', 'lease_expires_at', 'heartbeat_interval_s', 'recovered'}}
        encoded = json.dumps(stable_claim, sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        args = (self.namespace, identity.job_id, identity.attempt_no)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('''SELECT * FROM portal_v1_attempts WHERE namespace=?
                AND external_job_id=? AND attempt_no=?''', args).fetchone()
            if prior:
                if (prior['worker_id'] != self.worker_id or prior['fence_token'] != identity.fence_token
                        or prior['claim_hash'] != digest or prior['execution_id'] != execution_id):
                    raise BindingConflict('This attempt identity was reused with different work.')
                return {**dict(prior), 'created_now': False}

            previous = db.execute('''SELECT max(attempt_no) AS attempt_no FROM portal_v1_attempts
                WHERE namespace=? AND external_job_id=?''', args[:2]).fetchone()
            if previous['attempt_no'] is not None and previous['attempt_no'] >= identity.attempt_no:
                raise BindingConflict('A newer portal attempt is already recorded locally.')
            binding = db.execute('''SELECT * FROM portal_v1_conversations
                WHERE namespace=? AND external_id=?''', (self.namespace, cid)).fetchone()
            now = time.time()
            if binding:
                if (binding['kind'] != kind or binding['closeout_form_id'] != closeout_id
                        or (kind == 'general' and binding['owner_user_id'] != owner)):
                    raise BindingConflict('This portal conversation belongs to a different scope.')
                local_cid = binding['local_id']
            else:
                local_cid = new_id()
                title = 'T1 closeout' if kind == 'closeout' else 'Portal conversation'
                db.execute('INSERT INTO conversations VALUES(?,?,?,NULL)', (local_cid, title, now))
                db.execute('INSERT INTO portal_v1_conversations VALUES(?,?,?,?,?,?)',
                           (self.namespace, cid, local_cid, kind, owner, closeout_id))
            if db.execute("SELECT id FROM jobs WHERE conversation_id=? AND status IN ('queued','running','waiting','cancelling')", (local_cid,)).fetchone():
                raise BindingConflict('The previous local task has not stopped.')
            jid = new_id()
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,NULL,NULL,?)',
                       (jid, local_cid, prompt, 'queued', 'autonomous', now, '[]'))
            db.execute('''INSERT INTO portal_v1_attempts
                (namespace,external_job_id,worker_id,attempt_no,fence_token,execution_id,
                 local_job_id,claim_hash,claim_json,state,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                       (self.namespace, identity.job_id, self.worker_id, identity.attempt_no,
                        identity.fence_token, execution_id, jid, digest, encoded, 'prepared', now))
            db.execute('INSERT INTO events(conversation_id,job_id,kind,data,created) VALUES(?,?,?,?,?)',
                       (local_cid, jid, 'user', json.dumps({'text': prompt, 'attachments': []}), now))
            db.execute('INSERT INTO events(conversation_id,job_id,kind,data,created) VALUES(?,?,?,?,?)',
                       (local_cid, jid, 'portal_binding', json.dumps(asdict(identity)), now))
            row = db.execute('SELECT * FROM portal_v1_attempts WHERE namespace=? AND external_job_id=? AND attempt_no=?', args).fetchone()
            return {**dict(row), 'created_now': True}
