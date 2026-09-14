# ClearForm Hub worker protocol v1

The portal-v1 adapter is under development on `feat/clearhouse-portal-v1`.
It is not connected to `PortalWorker` yet. Existing installations continue to
use the optional legacy protocol documented in `PORTAL-PROTOCOL.md`.

## Implemented components

- `portal_contract.py` loads a reviewed, packaged JSON Schema snapshot. Both
  outgoing requests and incoming receipts are validated offline. Contract
  provenance is recorded beside the snapshot in `clara/contracts/README.md`.
- `portal_transport.py` sends worker requests to a configured HTTPS
  `/functions/v1` endpoint, with contract version and worker-key headers. It
  follows no redirects and does not expose response bodies in errors. A timeout
  means no validated receipt was obtained; it does not mean no work happened.
- `portal_lease.py` uses an exact job/worker/attempt/fence identity and a
  conservative monotonic deadline. Expiration is irreversible. The executor
  watchdog stops local execution on lease loss and awaits tool cleanup.
- `portal_journal.py` persists the original report before sending. Retrying a
  report reuses its original payload and key; a receipt cannot be replaced.
- `portal_bindings.py` atomically binds portal conversations to separate local
  histories and portal attempts to local jobs. It does not enqueue work.
  Restarted work is interrupted, never automatically replayed.
- `portal_delivery.py` pages the frozen message range, rejects changing or
  incomplete pages, saves messages before acknowledging delivery, and retries
  a lost acknowledgement without creating or replaying a job. The executor's
  portal dispatch method requires that acknowledgement and a live lease, and
  durably marks an attempt dispatched before queueing it.
- `portal_artifacts.py` snapshots a published attachment from the same
  conversation, verifies its recorded size/hash, and uploads exact bytes to an
  allocation on the configured portal's storage origin. Worker credentials are
  not sent to storage. Interrupted transfers retain an unknown outcome for
  object verification. Successful transfer is not tax-document verification.
- `portal_usage.py` maps one attempt's measured elapsed/waiting time, reported
  tokens and SDK API estimate. Missing values remain unknown. These figures
  cannot calculate remaining Max subscription allowance.
- The trusted portal preparation profile keeps required PDF/source-copy/
  application/signing/storage evidence and human review. Laureen handles
  invoicing. The server commits Ready to Email after receiving the result;
  that portal commit is not a prerequisite to finishing local preparation.
  Model-provided context flags cannot remove obligations from other workflows.

## Integration still required

1. Review the final portal contract and actual handlers. The current snapshot
   fixes the busy-heartbeat discriminator and passes its Python positive and
   negative fixtures; this is not validation of live server behavior.
2. Connect version dispatch, configuration and worker enrollment. Reserve the
   local executor before claim, persist the stable claim/message window, fetch
   every page and obtain the exact delivery acknowledgement before execution.
3. Connect independent heartbeat/command polling, durable questions and reply
   acknowledgement. Stop takes precedence over an answer. A lost claim response
   recovers its existing attempt; it never authorizes a second desktop task.
4. Map current evidence to stable member IDs, document types and tax year, send
   artifacts/results, and report observed quiescence before releasing the slot.
   A server receipt and a completed model response are different facts.
5. Verify SQL concurrency, authenticated portal UI and the real Windows/RDP
   workflow before enabling execution or issuing an installation update.

No inbound Windows desktop-control listener is introduced. Secrets belong in
the configured credential provider, not this repository or task logs.
