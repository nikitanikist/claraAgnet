# ClearForm Hub worker protocol v1

The portal-v1 adapter is under development on `feat/clearhouse-portal-v1`.
`PortalWorker` dispatches explicitly configured protocol-v1 connections to the
new runtime. Existing installations retain the optional legacy protocol in
`PORTAL-PROTOCOL.md`. No v1 configuration is enabled by installation or update,
and this branch has not been accepted for Windows release.

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
- `portal_intake.py` connects a positive authenticated claim to delivery,
  the scoped task prompt, the correct workflow and dispatch. It requires an
  already reserved executor. A repeated claim returns its existing local task
  for recovery and never enqueues it again. It is not yet connected to a
  Windows release. Ordinary information requests
  do not create a formal tax workflow or need a closeout review checkpoint.
- `portal_inputs.py` downloads every assigned source attachment before intake
  acknowledges delivery or dispatches execution. It verifies attachment identity,
  uses a separate credential-free client for signed storage URLs, bounds file
  and task sizes, and records local hashes without saving signed URLs. A failed
  later attachment leaves the task unstarted; an unchanged earlier download can
  be reused. Lease loss cancels a blocked transfer and removes its partial file.
- `portal_artifacts.py` snapshots a published attachment from the same
  conversation, verifies its recorded size/hash, and uploads exact bytes to an
  allocation on the configured portal's storage origin. The allocation must
  preserve the original client filename, independently of its unique storage
  path. Worker credentials are
  not sent to storage. Interrupted transfers retain an unknown outcome for
  object verification. Successful transfer is not tax-document verification.
- `portal_documents.py` maps the complete verified PDF evidence set to the
  assignment's exact member IDs, tax year and portal document types. It rejects
  missing/conflicting files, rechecks source hashes, and reuses immutable local
  published snapshots. It does not claim any file has reached OneDrive.
- `portal_outputs.py` and the task-scoped `record_portal_delivery` tool bind
  required PDFs to each member's PandaDoc record and observed OneDrive files.
  Fresh Chrome observations must match the recipient, business key, file/folder
  IDs, original filenames and exact byte counts. These are worker observations;
  the reported source hashes are not independent OneDrive hash verification.
  The tool returns checkpoint proofs and cannot approve a workflow or send email.
- `portal_results.py` prepares the exact PDF attachments and delivery records
  for the result endpoint. A stopped or incomplete task reports review instead
  of requesting successful handoff. The durable result is reused after a lost
  receipt or restart without recomputing usage, re-uploading files or starting
  another task. This component does not release the worker reservation.
- `portal_usage.py` maps one attempt's measured elapsed/waiting time, reported
  tokens and SDK API estimate. Missing values remain unknown. These figures
  cannot calculate remaining Max subscription allowance.
- `portal_control.py` relays short questions with separate context/details,
  maps choice labels to their full answers, and records command application
  before acknowledging it. Stop takes priority over simultaneous answers;
  losing an acknowledgement never applies the answer a second time. A busy
  heartbeat without an actual renewed lease stops the local task.
  Undeliverably long questions are rejected before entering the waiting state,
  allowing the model to rephrase without silently discarding context.
- `portal_session.py` runs heartbeat, controls and progress independently while
  an assigned local task executes or its result is delivered. A blocked chat
  response cannot prevent Stop or the lease watchdog from cancelling work.
  Local completion keeps the connection and reservation for result delivery;
  closing the session never releases the desktop or replays execution.
- `portal_runtime.py` serializes claim, complete intake, execution, final
  progress draining, result reporting and observed quiescence. It persists the
  worker reservation before a claim request and retains it on ambiguous errors.
  Input downloading has its own heartbeat and stop watchdog. After restart,
  a saved result can be reported again, but its model task cannot run again.
  Confirmed local quiescence plus the server release receipt clears the
  reservation. An interrupted intake or execution without a staged result
  reports its actual quiescence inventory without manufacturing a successful
  result or zero usage. An intake with no persisted binding cannot have
  dispatched execution. Unconfirmed actions retain their hold for operator
  review. A newer positive claim from the portal can transfer the reservation
  after operator reconciliation: the server refuses new claims while held.
  Negative replies and copies of the old claim never release or replay it.
  The old attempt/history remains saved, and the newly issued attempt is
  persisted before dispatch, including recovery of a lost new-claim receipt.
  Failed context delivery releases locally only when
  the server explicitly confirms release without a recovery hold.
- `portal_progress.py` relays completed chat text and concise activity with
  stable message IDs and a durable cursor. It excludes raw tool arguments and
  output from activity, preserves paragraph breaks, and cannot cross into
  another local task's events.
- `portal_quiescence.py` inventories running calls, unreturned tools,
  uncertain external writes and interrupted uploads. A returned desktop click
  alone is insufficient. The Windows observer now adds fresh session, process,
  window and print-queue observations for a qualified dedicated T1 worker.
  Unqualified sessions and uncertain actions retain their hold. This includes
  Clara's actual `run_command`, whose return cannot prove detached work stopped.
  Oversized unresolved
  reports retain the worker hold instead of silently losing actions.
- The trusted portal preparation profile keeps required PDF/source-copy/
  application/signing/storage evidence and human review. Laureen handles
  invoicing. The server commits Ready to Email after receiving the result;
  that portal commit is not a prerequisite to finishing local preparation.
  Model-provided context flags cannot remove obligations from other workflows.

## Integration still required

1. Confirm the deployed portal uses the reviewed contract/handlers. The bundled
   snapshot now includes finalization errors and exact failed-context outcomes.
   Its Python fixtures and runtime recovery tests pass; this is not validation
   of live server behavior.
2. Validate enrollment and the configured model account arrangement with the
   real Windows worker. Protocol v1 requires `protocol_version: 1`, the issued
   worker UUID, an HTTPS `/functions/v1` base URL, a `CLARA_PORTAL_` credential
   variable, and `authentication_reviewed: true` in the local `portal.json`.
   Configuration and credential changes require a restart. Keep `enabled: false`
   during setup. After the environment and credentials have been checked, enable
   it only for a supervised acceptance window with test assignments. General
   staff use waits until the connected acceptance checks pass.
3. Qualify the implemented Windows observer on the real dedicated RDP and validate
   operator recovery end to end. See WINDOWS-WORKER-HANDOFF.md. Keep automatic
   handoff unqualified during setup. After native observations and the first
   task's cleanup have been reviewed, qualify it for the supervised two-task
   queue test; retain qualification for general use only if that test passes.
   A successful tool return alone never releases the desktop.
4. Report observed Windows quiescence before releasing the slot. The current general-task upload types
   are limited to the portal's PDF/PNG/CSV/DOCX/XLSX allowlist; unsupported output
   types must be resolved before general attachment delivery is enabled.
   A server receipt and a completed model response are different facts.
5. Verify SQL concurrency, authenticated portal UI and the real Windows/RDP
   workflow before enabling general staff execution or issuing a release update.

No inbound Windows desktop-control listener is introduced. Secrets belong in
the configured credential provider, not this repository or task logs.
Configured `CLARA_PORTAL_` credential values are retained in service memory and
removed from the environment inherited by model and command subprocesses. The
legacy adapter uses the same provider so normal process sanitization does not
disable its configured connection. Credential rotation requires the configured
service restart; no model tool exposes the provider.

## Latest local validation

The development branch's Python suite passes 272 tests (plus a native Windows test that is skipped on macOS). The result delivery
tests use synthetic PDFs and mocked portal/storage receipts. They verify the
outbound payload and retry behavior, not an actual Ready to Email transition.
No real PandaDoc/OneDrive account, authenticated portal UI or Windows desktop
was exercised by these tests. This is not an installation or release notice.
Runtime tests cover the serial cycle, complete final-message draining, lost
claim/result receipts, reporting after a restart, Stop during blocked intake,
and retaining a hold for unconfirmed desktop activity. Model execution and
server receipts in these tests are simulated.
Additional cases cover the original allocation filename, ambiguous failed
context delivery, and reporting stopped intake/execution without a final result.

Operator-reconciliation tests cover a retained server hold, newer-attempt
resumption in the original conversation, lost newer-claim receipts, and
rejection of a recovered old claim as permission to replay. Server operator
reconciliation is simulated; no actual RDP action was observed.

The reviewed contract now includes finalization_in_progress and rejects
ambiguous failed-context outcomes while retaining generic recovery-hold replies.
A finalization-busy response preserves pending reporting without exposing server
message content; the local test verifies its explicit error classification.

When a portal continuation has unreviewed missing usage, Clara asks a short
question in the same portal chat before querying the model. Continue records
review of the exact usage snapshot without filling missing values or changing
limits. Keep paused, cancellation, and changed usage history do not grant that
review. Local-only workflows retain their existing Workflow review screen.
