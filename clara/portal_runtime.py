"""Serial outbound worker lifecycle, with durable holds across restarts.

This runner never releases a desktop merely because the model returned. The
quiescence observer must confirm that work is quiet, and the server must agree.
An interrupted execution is never automatically dispatched again.
"""
import asyncio
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import time
from uuid import uuid4

from . import __version__
from .portal_contract import ContractViolation
from .portal_intake import PortalIntake, PreparedAttempt, claim_lease
from .portal_journal import PortalJournal
from .portal_lease import AttemptIdentity, ExecutionLease, LeaseLost
from .portal_quiescence import observe_quiescence
from .portal_results import PortalResults
from .portal_session import PortalSession
from .portal_transport import PortalRejected, PortalUnavailable


class PortalRuntime:
    def __init__(self, config, store, manager, transport, worker_id, *, observer=observe_quiescence):
        self.config, self.store, self.manager = config, store, manager
        self.transport, self.worker_id, self.observer = transport, worker_id, observer
        self.journal = PortalJournal(store, transport.base_url)
        self.task = self.session = self.lease = None
        self.error = None
        self.closed = False

    def pending(self):
        return self.store.one('''SELECT * FROM portal_v1_cycles WHERE namespace=?
            AND worker_id=? AND finished IS NULL''', (self.transport.base_url, self.worker_id))

    def _update(self, cid, state, *, error=None, jid=None, claim=None):
        self.store.execute('''UPDATE portal_v1_cycles SET state=?,error=?,
            local_job_id=coalesce(?,local_job_id),claim_json=coalesce(?,claim_json) WHERE id=?''',
            (state, error, jid, json.dumps(claim, allow_nan=False) if claim is not None else None, cid))
        self.error = error

    async def start(self):
        if self.task or self.closed:
            raise ValueError('This portal runner has already started or closed.')
        prior = self.pending()
        if prior and not self.manager.reserve_execution(prior['id']):
            raise ValueError('The saved portal hold conflicts with current local execution.')
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while not self.closed:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Provider bodies, URLs and arbitrary exception text are not
                # suitable for the local status channel.
                self.error = 'Portal work needs review. Existing work and the worker hold have been preserved.'
            await asyncio.sleep(5)

    async def close(self):
        self.closed = True
        if self.lease:
            self.lease.fence('The portal worker is shutting down. Inspect existing work before resuming.')
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.session:
            await self.session.close()
        await self.transport.close()
        # No reservation or remote lock is cleared during shutdown.

    def _complete(self, cid):
        if (self.manager.execution_reservation != cid or self.manager.active_job
                or not self.manager.queue.empty()):
            raise ValueError('The executor is not ready to release this reservation.')
        self.store.execute("UPDATE portal_v1_cycles SET state='finished',finished=?,error=NULL WHERE id=?",
                           (time.time(), cid))
        self.manager.release_execution(cid, quiescent=True)
        self.error = None

    async def tick(self):
        cycle = self.pending()
        cid = cycle['id'] if cycle else str(uuid4())
        if not self.manager.reserve_execution(cid):
            return 'local_busy'
        if cycle is None:
            # Persist before the claim request. A lost response may have
            # allocated a remote slot; it must not make the executor look free.
            self.store.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,NULL,NULL,?,NULL,NULL)',
                (cid, self.transport.base_url, self.worker_id, 'claiming', time.time()))
            cycle = self.pending()
        if cycle['claim_json'] is not None:
            return await self._recover(cycle)
        if cycle['state'] != 'claiming':
            return 'held'
        try:
            reply = await self.transport.request('clara-claim',
                {'worker_id': self.worker_id, 'agent_version': __version__})
        except PortalUnavailable:
            self.error = 'The claim receipt was lost. Clara will recover the owned slot before accepting more work.'
            return 'claim_unknown'
        except PortalRejected:
            self._update(cid, 'held', error='The portal rejected the claim. Review the connection and existing worker hold.')
            return 'held'
        claim = reply.body
        if claim['claimed'] is not True:
            if claim.get('owned_job_id') or claim.get('reason') in {'recovery_hold', 'slot_busy'}:
                self._update(cid, 'held', error='The portal reports an existing worker hold. Review it before starting another task.')
                return 'held'
            self._complete(cid)
            return 'idle'
        self._update(cid, 'intake', claim=claim)
        try:
            self.lease = claim_lease(self.transport, reply, self.worker_id)
            prepared = await self._intake(reply, cid)
            self._update(cid, 'running', jid=prepared.local_job_id)
            if prepared.recovered:
                # A durable local binding is not permission to replay it.
                return await self._recover(self.pending())
            self.session = PortalSession(self.store, self.manager, self.transport,
                                         self.journal, prepared)
            self.session.start()
            await self.session.wait_for_execution()
            await self.session.flush_progress()
            timing = self.session.observe_timing()
            self._update(cid, 'reporting')
            await self._result(prepared, timing)
            self._update(cid, 'quiescing')
        except asyncio.CancelledError:
            raise
        except (PortalUnavailable, PortalRejected, LeaseLost, ValueError):
            self._update(cid, 'held', error='The attempt did not settle. Review saved progress; execution will not be replayed.')
            return 'held'
        finally:
            if self.session:
                await self.session.close()
                self.session = None
            if self.lease:
                self.lease.fence('Local execution ended. Only result and recovery reporting may continue.')
        return await self._quiesce(self.pending(), prepared)

    async def _intake(self, reply, cid):
        """Renew/stop independently while message pages or files are arriving."""
        lease = self.lease
        async def keepalive():
            while True:
                try:
                    lease.assert_active()
                    response = await self.transport.request('clara-heartbeat',
                        {**asdict(lease.identity), 'busy': True, 'stage': 'receiving_inputs'})
                    body = response.body
                    if body['stop_requested'] or not body.get('lease_expires_at') or body.get('state') in {
                            'stopping', 'stopped', 'cancelled', 'recovery_required', 'failed'}:
                        lease.fence('The portal stopped this task before intake finished.')
                        return
                    lease.acknowledge(lease.identity,
                        expires_at=datetime.fromisoformat(body['lease_expires_at'].replace('Z', '+00:00')),
                        server_time=datetime.fromisoformat(body['server_time'].replace('Z', '+00:00')),
                        request_started=response.request_started)
                except PortalUnavailable:
                    pass
                except (PortalRejected, ContractViolation, LeaseLost):
                    lease.fence('The portal no longer permits this task to start.')
                    return
                await asyncio.sleep(min(10, max(.01, lease.remaining_seconds / 3)))
        intake = asyncio.create_task(PortalIntake(self.config, self.store, self.manager,
            self.transport, self.worker_id).start_claim(reply, reservation_id=cid, lease=lease))
        heartbeat = asyncio.create_task(keepalive())
        watchdog = asyncio.create_task(lease.wait_until_lost())
        try:
            done, _ = await asyncio.wait((intake, watchdog), return_when=asyncio.FIRST_COMPLETED)
            if watchdog in done:
                raise watchdog.result()
            return await intake
        finally:
            for task in (intake, heartbeat, watchdog):
                task.cancel()
            await asyncio.gather(intake, heartbeat, watchdog, return_exceptions=True)

    async def _result(self, prepared, timing):
        result = PortalResults(self.config, self.store, self.transport, self.journal)
        try:
            return await result.deliver(prepared, timing)
        finally:
            await result.close()

    async def _recover(self, cycle):
        claim = json.loads(cycle['claim_json'])
        binding = self.store.one('''SELECT * FROM portal_v1_attempts WHERE namespace=?
            AND external_job_id=? AND worker_id=? AND attempt_no=? AND fence_token=?''',
            (self.transport.base_url, claim['job_id'], self.worker_id, claim['attempt_no'], claim['fence_token']))
        if not binding:
            self._update(cycle['id'], 'held', error='Intake was interrupted before dispatch. Review the portal attempt before releasing this worker.')
            return 'held'
        jid = binding['local_job_id']
        await self.manager.cancel(jid)
        if self.manager.active_job or not self.manager.queue.empty():
            return 'held'
        identity = AttemptIdentity(claim['job_id'], self.worker_id, claim['attempt_no'], claim['fence_token'])
        lease = ExecutionLease(identity, clock=self.transport.clock)
        lease.fence('This is recovery reporting, not permission to execute.')
        prepared = PreparedAttempt(jid, lease, True)
        result = self.store.one('''SELECT id FROM portal_v1_outbox WHERE namespace=? AND
            external_job_id=? AND worker_id=? AND attempt_no=? AND fence_token=? AND operation='clara-result'
            AND request_key=?''', (self.transport.base_url, identity.job_id, identity.worker_id,
                                  identity.attempt_no, identity.fence_token, 'result-' + jid))
        if not result:
            self._update(cycle['id'], 'held', jid=jid,
                error='The task was interrupted before its result was recorded. Review its existing outputs before resuming.')
            return 'held'
        # PortalResults reuses the staged payload verbatim; timing here is not
        # used to manufacture a new usage report after a process restart.
        try:
            await self._result(prepared, {'wall_seconds': 0, 'waiting_seconds': 0})
        except (PortalUnavailable, PortalRejected):
            self.error = 'The saved result still needs a portal receipt. Clara will retry reporting without repeating execution.'
            return 'held'
        return await self._quiesce(cycle, prepared)

    async def _quiesce(self, cycle, prepared):
        identity = prepared.lease.identity
        report = self.observer(self.store, self.manager, self.transport.base_url, identity, prepared.local_job_id)
        # Compare actual current observations with a previous pending report.
        # Retrying unchanged observations reuses their original timestamp/key.
        fingerprint = hashlib.sha256(json.dumps({k:v for k,v in report.items() if k != 'observed_at'},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        key = 'quiet-' + cycle['id'] + '-' + fingerprint
        prior = self.store.one('''SELECT payload FROM portal_v1_outbox WHERE namespace=? AND
            external_job_id=? AND worker_id=? AND attempt_no=? AND fence_token=? AND
            operation='clara-quiesce' AND request_key=?''',
            (self.transport.base_url, identity.job_id, identity.worker_id, identity.attempt_no, identity.fence_token, key))
        payload = json.loads(prior['payload']) if prior else {**asdict(identity), 'report': report}
        receipt = await self.transport.report(self.journal, identity, 'clara-quiesce', key, payload)
        if report['complete'] and receipt['quiescent'] and not receipt['recovery_hold']:
            self._complete(cycle['id'])
            return 'finished'
        self._update(cycle['id'], 'held', error='Some desktop actions are still unconfirmed. The worker remains reserved for review.')
        return 'held'
