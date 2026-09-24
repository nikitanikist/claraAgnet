"""Serial outbound worker lifecycle, with durable holds across restarts.

This runner never releases a desktop merely because the model returned. The
quiescence observer must confirm that work is quiet, and the server must agree.
An interrupted execution is never automatically dispatched again.
"""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from uuid import uuid4

from . import __version__
from .diagnostics import redact_text
from .portal_contract import ContractViolation
from .portal_intake import PortalIntake, PreparedAttempt, claim_lease
from .portal_journal import PortalJournal
from .portal_lease import AttemptIdentity, ExecutionLease, LeaseLost
from .portal_quiescence import observe_quiescence
from .portal_results import PortalResults
from .portal_session import PortalSession
from .portal_transport import PortalRejected, PortalUnavailable
from .windows_session import KEEPALIVE_S, touch_input


CLAIM_RETRY_S = 30
PRESENCE_INTERVAL_S, PRESENCE_MIN_S, PRESENCE_MAX_S = 60, 10, 120
# The Windows observer needs a clean desktop to stay clean for 3 s before it
# calls it quiet. A little longer than that, so a second look can settle it.
SETTLE_RECHECK_S = 3.1
RUNTIME_LOG_BYTES = 5 * 1024 * 1024
# Quoted strings holding a separator, absolute POSIX paths, Windows drive and UNC paths.
# Bare paths run to the end of the line: a client folder may contain spaces, and
# over-masking trailing prose is fine for a cause-only log line.
PATH_TOKEN = re.compile(r'''["'][^"'\n]*[/\\][^"'\n]*["']|(?<![\w/])/[^\s"'/][^"'\n]*|\b[A-Za-z]:[\\/][^"'\n]*|\\\\[^"'\n]*''')


class PortalRuntime:
    def __init__(self, config, store, manager, transport, worker_id, *, observer=observe_quiescence):
        self.config, self.store, self.manager = config, store, manager
        self.transport, self.worker_id, self.observer = transport, worker_id, observer
        self.journal = PortalJournal(store, transport.base_url)
        self.task = self.session = self.lease = None
        self.error = None
        self.closed = False
        # Transport-clock timers: next unclaimed-hold claim retry, last idle heartbeat.
        self._claim_retry_at = None
        self._presence_at, self._presence_interval = None, PRESENCE_INTERVAL_S
        self._keepalive_at, self.touch = None, touch_input
        self.settle_recheck_s = SETTLE_RECHECK_S

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
            delay = 5
            try:
                state = await self.poll()
                # Pick up idle work promptly; after finishing, immediately ask
                # for the next queued item. Recovery retains its slower retry.
                delay = 2 if state == 'idle' else 0 if state == 'finished' else 5
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Provider bodies, URLs and arbitrary exception text are not
                # suitable for the local status channel; a redacted line goes
                # to the local log so the cause can still be found.
                self._diagnose(error)
                self.error = ('Portal work needs review. Existing work and the worker hold have been preserved. ('
                              + type(error).__name__ + ')')
            await asyncio.sleep(delay)

    async def poll(self):
        state = await self.tick()
        if state in {'held', 'claim_unknown'}:
            await self._presence()
        self._keep_session_alive()
        return state

    def _keep_session_alive(self):
        """Remote Desktop Services counts only input as activity, and a locked client sends none.

        A zero-net mouse move every few minutes keeps the dedicated session from being
        disconnected for inactivity while Clara is idle, held, or waiting for a person's
        answer. It is skipped while a task executes so it never interleaves with Clara's
        own desktop actions."""
        job = self.store.job(self.manager.active_job) if self.manager.active_job else None
        if job and job['status'] != 'waiting':
            return
        now = self.transport.clock()
        if self._keepalive_at is not None and now - self._keepalive_at < KEEPALIVE_S:
            return
        self._keepalive_at = now
        try:
            self.touch()
        except Exception:
            pass  # Presence on the desktop is best effort; it never changes state.

    async def _presence(self):
        """A held worker sends nothing else, and quiesce replays do not count as
        a heartbeat, so the portal would label the live process offline. This
        announces presence only; it never claims, releases or changes state."""
        if self.session or self.manager.active_job or not self.manager.queue.empty():
            return  # A session sends busy heartbeats; local work in hand is not idle either.
        now = self.transport.clock()
        if self._presence_at is not None and now - self._presence_at < self._presence_interval:
            return
        self._presence_at = now
        try:
            reply = await self.transport.request('clara-heartbeat', {'worker_id': self.worker_id, 'busy': False})
        except (PortalUnavailable, PortalRejected, ContractViolation, ValueError):
            return  # Credential problems already surface through the claim path.
        interval = reply.body.get('heartbeat_interval_s')
        self._presence_interval = max(PRESENCE_MIN_S, min(
            interval if type(interval) is int else PRESENCE_INTERVAL_S, PRESENCE_MAX_S))

    def _diagnose(self, error):
        if isinstance(error, OSError):
            # OSError text carries filenames, which may be client folders.
            message = f'errno={error.errno} {error.strerror or ""}'
        else:
            message = redact_text(str(error))
        message = re.sub(r'\b\w+://\S+', '[url]', message)
        message = PATH_TOKEN.sub('[path]', message)
        message = re.sub(r'\s+', ' ', message).strip()[:500]
        try:
            path = self.config.data / 'logs' / 'portal-runtime.log'
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > RUNTIME_LOG_BYTES:
                path.write_text('')
            with path.open('a', encoding='utf-8') as log:
                log.write(f'{datetime.now(timezone.utc).isoformat()} {type(error).__name__} {message}\n')
        except OSError:
            pass

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
            # A rejected or ambiguous first claim leaves a hold without a claim.
            # The portal may have cleared it since; ask again slowly instead of
            # waiting for a manual edit. Between retries nothing is sent.
            now = self.transport.clock()
            if self._claim_retry_at is None:
                self._claim_retry_at = now + CLAIM_RETRY_S
            if now < self._claim_retry_at:
                return 'held'
        self._claim_retry_at = self.transport.clock() + CLAIM_RETRY_S
        try:
            reply = await self.transport.request('clara-claim',
                {'worker_id': self.worker_id, 'agent_version': __version__})
        except PortalUnavailable:
            self.error = 'The claim receipt was lost. Clara will recover the owned slot before accepting more work.'
            return 'claim_unknown'
        except (PortalRejected, ContractViolation):
            self._update(cid, 'held', error='The portal rejected the claim. Review the connection and existing worker hold.')
            return 'held'
        claim = reply.body
        if claim['claimed'] is not True:
            if claim.get('reason') == 'context_unavailable':
                # A failed context transfer may already own a remote slot.
                # Release only on the explicit, internally consistent receipt.
                released = (claim.get('attempt_released') is True
                            and claim.get('recovery_hold') is False
                            and not claim.get('owned_job_id'))
                if not released:
                    self._update(cid, 'held', error='The portal could not deliver the task and has not confirmed release. Review the existing worker hold.')
                    return 'held'
            if claim.get('recovery_hold') is True or claim.get('owned_job_id') or claim.get('reason') in {'recovery_hold', 'slot_busy'}:
                self._update(cid, 'held', error='The portal reports an existing worker hold. Review it before starting another task.')
                return 'held'
            self._complete(cid)
            return 'idle'
        return await self._execute_claim(cid, reply)

    async def _execute_claim(self, cid, reply):
        self._update(cid, 'intake', claim=reply.body)
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
            if cycle['local_job_id'] or self.manager.active_job or not self.manager.queue.empty():
                self._update(cycle['id'], 'held', error='The interrupted intake has conflicting local work. Review it before releasing this worker.')
                return 'held'
            # Bindings are persisted before dispatch. Without one, this claim
            # could only have received inputs, never run model/desktop actions.
            # Report that observed state; the server still decides whether the
            # attempt is stopped and whether its remote slot can be released.
            return await self._quiesce(cycle, None, report={
                'finished':['intake:no-execution'], 'in_flight':[], 'unknown':[],
                'observed_at':datetime.now(timezone.utc).isoformat(), 'complete':True})
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
            # Recovery does not fabricate a successful result, zero usage or
            # another model run. It must still deliver the actual stopped/unknown
            # action inventory so a person can reconcile it in the portal.
            return await self._quiesce(cycle, prepared)
        # PortalResults reuses the staged payload verbatim; timing here is not
        # used to manufacture a new usage report after a process restart.
        try:
            await self._result(prepared, {'wall_seconds': 0, 'waiting_seconds': 0})
        except (PortalUnavailable, PortalRejected):
            self.error = 'The saved result still needs a portal receipt. Clara will retry reporting without repeating execution.'
            return 'held'
        return await self._quiesce(cycle, prepared)

    async def _quiesce(self, cycle, prepared, *, report=None):
        claim = json.loads(cycle['claim_json'])
        identity = (prepared.lease.identity if prepared else
                    AttemptIdentity(claim['job_id'], self.worker_id, claim['attempt_no'], claim['fence_token']))
        if report is None:
            report = self.observer(self.store, self.manager, self.transport.base_url, identity, prepared.local_job_id)
            if ('external-desktop-state-unconfirmed' in report['unknown'] and
                    self.manager.windows_handoff is not None):
                activity = await self.manager.windows_handoff.observe(prepared.local_job_id)
                # A clean desktop's first quiet look only starts its settling
                # window, so a finished closeout reported "not quiet" once and
                # held the worker for a poll - flashing "held for review" and a
                # review prompt over work that was done. Look again, in full,
                # once the window has passed. Anything that appears meanwhile
                # still counts; the settling item is never simply dropped.
                if not activity['unknown'] and activity['in_flight'] == ['windows-settling']:
                    await asyncio.sleep(self.settle_recheck_s)
                    activity = await self.manager.windows_handoff.observe(prepared.local_job_id)
                report['in_flight'] = sorted(set(report['in_flight'] + activity['in_flight']))
                report['unknown'] = sorted(set(report['unknown'] + activity['unknown']))
                if activity['complete']:
                    report['unknown'].remove('external-desktop-state-unconfirmed')
                    report['finished'].append('windows-session-observed-quiet')
                    report['finished'] = report['finished'][-200:]
                report['complete'] = not report['in_flight'] and not report['unknown']
                if len(report['in_flight']) > 200 or len(report['unknown']) > 200:
                    raise ValueError('Windows activity report exceeds the portal limit; retain the worker hold.')
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
        # Whenever nothing is in flight, ask the portal for work: it refuses while
        # it still holds this worker, and a positive claim means a person has
        # settled the old attempt (continued or cancelled it), so the runtime can
        # move on. A negative reply changes nothing locally.
        if not report['in_flight']:
            return await self._reconciled_claim(cycle, identity)
        return 'held'

    async def _reconciled_claim(self, cycle, previous):
        """Accept new work only after the portal's recovery hold was cleared.

        The claim endpoint atomically refuses work while this worker has a
        recovery hold. A negative/ambiguous response never releases the local
        reservation. A newer positive claim is permission for THAT attempt,
        not permission to replay the stopped attempt or clear its history.
        """
        if (self.manager.execution_reservation != cycle['id'] or
                self.manager.active_job or not self.manager.queue.empty()):
            return 'held'
        try:
            reply = await self.transport.request('clara-claim',
                {'worker_id':self.worker_id, 'agent_version':__version__})
        except (PortalUnavailable, PortalRejected, ContractViolation):
            return 'held'
        claim = reply.body
        if claim['claimed'] is not True:
            return 'held'
        if (self.manager.execution_reservation != cycle['id'] or
                self.manager.active_job or not self.manager.queue.empty()):
            # An issued claim can be recovered on the next poll. Do not transfer
            # the executor if local state changed while the request was pending.
            return 'held'
        if (claim['fence_token'] <= previous.fence_token or
                (claim['job_id'] == previous.job_id and claim['attempt_no'] <= previous.attempt_no)):
            # A recovered copy of the old claim cannot authorize replay.
            return 'held'
        cid = str(uuid4())
        # Keep the old cycle and its receipts as audit history. Save the new
        # claimed slot before transferring the in-process reservation, so a
        # crash here restores a hold on the newly issued attempt.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE portal_v1_cycles SET state='reconciled',finished=?,error=NULL WHERE id=? AND finished IS NULL",
                                 (time.time(), cycle['id']))
            if changed.rowcount != 1:
                raise ValueError('The saved recovery cycle changed.')
            db.execute('INSERT INTO portal_v1_cycles VALUES(?,?,?,?,?,NULL,?,NULL,NULL)',
                (cid, self.transport.base_url, self.worker_id, 'intake', json.dumps(claim, allow_nan=False), time.time()))
        self.manager.release_execution(cycle['id'], quiescent=True)
        if not self.manager.reserve_execution(cid):
            raise ValueError('The newly issued portal attempt could not reserve this executor.')
        # No await separates the local reservation transfer. Only the freshly
        # authenticated claim proceeds through normal intake and its watchdog.
        return await self._execute_claim(cid, reply)
