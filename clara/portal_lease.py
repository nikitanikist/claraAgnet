"""Local execution fencing, independent of the portal's HTTP wire format.

A server lease is permission to start work for one attempt, not proof that a
previous external action has finished. Expiry is irreversible for this object;
recovery requires a new explicitly authorized attempt.
"""
from dataclasses import dataclass
from datetime import datetime
import math
import time


class LeaseLost(RuntimeError):
    """The executor must stop starting actions and preserve recovery state."""


@dataclass(frozen=True)
class AttemptIdentity:
    job_id: str
    worker_id: str
    attempt_no: int
    fence_token: int

    def __post_init__(self):
        if not all(isinstance(value, str) and value.strip()
                   for value in (self.job_id, self.worker_id)):
            raise ValueError('An attempt needs job and worker identities.')
        if any(type(value) is not int or value < 1
               for value in (self.attempt_no, self.fence_token)):
            raise ValueError('Attempt and fencing numbers must be positive integers.')


class ExecutionLease:
    def __init__(self, identity, *, clock=time.monotonic, safety_margin=5.0,
                 maximum_seconds=120.0):
        if not isinstance(identity, AttemptIdentity):
            raise ValueError('Provide a validated attempt identity.')
        if not (math.isfinite(safety_margin) and math.isfinite(maximum_seconds)
                and 0 < safety_margin < maximum_seconds):
            raise ValueError('The lease needs a positive safety margin below its duration.')
        self.identity = identity
        self.clock = clock
        self.safety_margin = safety_margin
        self.maximum_seconds = maximum_seconds
        self.deadline = None
        self.last_request_started = None
        self.reason = None

    def fence(self, reason='Portal execution permission ended.'):
        # Only fixed diagnostic strings should be passed here, never HTTP bodies.
        if self.reason is None:
            self.reason = reason

    def assert_active(self):
        if self.reason is None and self.deadline is not None and self.clock() >= self.deadline:
            self.fence('Portal lease expired; inspect existing work before resuming.')
        if self.reason is not None or self.deadline is None:
            raise LeaseLost(self.reason or 'No acknowledged portal lease is available.')

    def acknowledge(self, identity, *, expires_at, server_time, request_started):
        """Renew from an exact server acknowledgement using a monotonic deadline.

        server_time must be the server timestamp accompanying the acknowledgement
        (for example its HTTP Date), not the Windows wall clock. Starting the
        duration at request send time conservatively includes network latency.
        An old delayed response cannot extend a more recently acknowledged lease.
        """
        if self.reason is not None:
            raise LeaseLost(self.reason)
        if self.deadline is not None:
            self.assert_active()
        if identity != self.identity:
            self.fence('Portal acknowledgement belongs to a different attempt.')
            raise LeaseLost(self.reason)
        if not all(isinstance(value, datetime) and value.utcoffset() is not None
                   for value in (expires_at, server_time)):
            self.fence('Portal acknowledgement has no valid server timestamps.')
            raise LeaseLost(self.reason)
        if not isinstance(request_started, (int, float)) or not math.isfinite(request_started) or request_started > self.clock():
            self.fence('Portal acknowledgement has invalid request timing.')
            raise LeaseLost(self.reason)
        if self.last_request_started is not None and request_started < self.last_request_started:
            return False
        duration = min((expires_at - server_time).total_seconds(), self.maximum_seconds)
        candidate = request_started + duration - self.safety_margin
        if candidate <= self.clock():
            self.fence('Portal lease expired before its acknowledgement arrived.')
            raise LeaseLost(self.reason)
        self.deadline = candidate
        self.last_request_started = request_started
        return True

    @property
    def remaining_seconds(self):
        try:
            self.assert_active()
        except LeaseLost:
            return 0.0
        return max(0.0, self.deadline - self.clock())
