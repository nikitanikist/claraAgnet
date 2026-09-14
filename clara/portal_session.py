"""Keep an assigned attempt connected while execution or result delivery runs.

Heartbeat, Stop/answer controls and progress have independent loops. A slow
chat receipt must not delay Stop or prevent the execution lease from expiring.
This component never claims work, releases the desktop or retries execution.
"""
import asyncio
import time

from .portal_control import PortalControl
from .portal_lease import LeaseLost
from .portal_progress import PortalProgress
from .portal_transport import PortalUnavailable


TERMINAL = frozenset({'completed', 'needs_review', 'incomplete', 'failed',
                      'cancelled', 'interrupted'})


class PortalSession:
    def __init__(self, store, manager, transport, journal, prepared, *, clock=time.monotonic):
        self.store, self.manager = store, manager
        self.lease, self.local_job_id = prepared.lease, prepared.local_job_id
        self.control = PortalControl(store, manager, transport, journal, self.lease, self.local_job_id)
        self.progress = PortalProgress(store, transport, journal, self.lease, self.local_job_id)
        self.clock = clock
        self.started = self.last_observed = clock()
        self.waiting_seconds = 0.0
        self.was_waiting = False
        self.tasks = []
        self.error = None
        self.closed = False

    def start(self):
        if self.tasks or self.closed:
            raise ValueError('This portal session has already started or closed.')
        self.lease.assert_active()
        self.tasks = [asyncio.create_task(self._loop(self.control.heartbeat, 10)),
                      asyncio.create_task(self._loop(self.control.poll_commands, 1)),
                      asyncio.create_task(self._loop(self._publish, 1)),
                      asyncio.create_task(self._watch_lease())]

    async def _publish(self):
        await self.control.publish_questions()
        await self.progress.flush()

    async def _stop(self, reason):
        self.lease.fence(reason)
        self.error = reason
        await self.manager.cancel(self.local_job_id)

    async def _loop(self, operation, interval):
        while not self.closed:
            try:
                self.lease.assert_active()
                next_interval = await operation()
                # The server recommends heartbeat timing. Keep enough room to
                # observe expiration even if its advertised interval is large.
                if type(next_interval) is int:
                    interval = min(10, max(1, next_interval))
            except LeaseLost:
                return
            except PortalUnavailable:
                # Only control polling and durable reports repeat here. The
                # independent watchdog cancels execution at the last confirmed
                # deadline; an unavailable portal never extends permission.
                pass
            except asyncio.CancelledError:
                raise
            except Exception:
                # Do not forward provider payloads, signed links or client data
                # from arbitrary exception strings into the status channel.
                await self._stop('The portal connection rejected this attempt. Review its saved progress.')
                return
            await asyncio.sleep(min(interval, max(0.01, self.lease.remaining_seconds / 3)))

    async def _watch_lease(self):
        error = await self.lease.wait_until_lost()
        await self._stop(str(error))

    def observe_timing(self):
        now = self.clock()
        if self.was_waiting:
            self.waiting_seconds += max(0, now - self.last_observed)
        self.last_observed = now
        job = self.store.job(self.local_job_id)
        self.was_waiting = bool(job and job['status'] == 'waiting')
        return {'wall_seconds': max(0, now - self.started),
                'waiting_seconds': self.waiting_seconds}

    async def wait_for_execution(self):
        if not self.tasks:
            raise ValueError('Start the session before waiting for execution.')
        while not self.closed:
            self.observe_timing()
            job = self.store.job(self.local_job_id)
            if not job:
                await self._stop('The local portal task is unavailable. Review the worker before resuming.')
                raise ValueError(self.error)
            if job['status'] in TERMINAL and self.manager.active_job != self.local_job_id:
                # Heartbeat/control remain active for artifact/result delivery.
                # Terminal local status alone cannot release the worker slot.
                return job
            await asyncio.sleep(0.1)
        raise ValueError('The portal session closed before execution settled.')

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.observe_timing()
        self.lease.fence('The local portal session closed. Preserve existing work for review.')
        await self.manager.cancel(self.local_job_id)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        # The owner still has to inspect quiescence and obtain the server's
        # release receipt. Never clear its execution reservation here.
