# Dedicated Windows worker handoff

## Ordinary portal requests

General conversations use their own completed-result receipt (`not_applicable`
for closeout handoff). They do not need a T1 or Ready-to-Email receipt. The local
executor and all tool calls must finish, external operation reservations and
attachments must settle, and fresh observations must show the same unlocked
dedicated Windows session with no printing. Existing application windows may
remain open. A newly opened visible application may be the requested result;
its presence alone does not reserve the computer forever. Newly observed
background processes and script/model controllers still require review, even
when they have a window. Three seconds of settled observations are required.

This does not qualify the separate TaxPrep handoff or release an interrupted
attempt. The original baseline and result receipt remain unchanged. General
requests also skip the TaxPrep-specific document/upload cleanup instruction.

Development implementation; the real Clearhouse RDP is not yet qualified. The user confirmed on 2026-09-15 that the Windows account clara.agent will be dedicated to Clara.

## What is implemented

Before a portal model task starts, Clara saves a read-only baseline from the separate desktop Python. It records the Windows account/session, boot and controller process identity, all current-session processes with creation times, visible window handles/classes, and current account print jobs. It omits document titles, command lines, printer names, credentials and client paths. The baseline is tied to the local job and is never replaced during recovery.

Some RDP systems omit process owner SIDs from WTS enumeration. The probe attempts a limited token query and still tracks a process by PID and creation time when its SID stays unavailable; it never ignores a process based on its name. Missing creation identity remains an observation error. Diagnostic metadata identifies unresolved owners and window sizes. Zero-size shell helper windows are excluded from the visible app list; their processes remain tracked.

ThumbnailDeviceHelperWnd and EdgeUiInputTopWndClass are also shell surfaces only when owned by the process returned by GetShellWindow. Ordinary File Explorer folder windows still block a clean baseline. The Windows boot-time estimate may jitter by up to two seconds; account, session and the controller's PID plus exact creation time must still match. New process identities are always tracked.

After result reporting, WindowsHandoff takes fresh observations. Automatic release requires all of the following:

- The configured session is dedicated and has passed Windows qualification.
- The baseline was complete and interactive, with no current-account print job pending. Programs that were already open (a browser, a chat client, a TaxPrep instance) are recorded as baseline notes; they belong to whoever opened them and never block a start or a release.
- The same Windows account, session, boot and controller process remain. A reused PID with a different creation time is a different process.
- Every process the task started and every new visible window has gone, and all configured queues were readable with no remaining current-account print job. Paused, retained or failed print jobs are not treated as finished.

**What counts as a leftover.** A leftover is something Clara started during the task that is still running or open when she finishes: a process that did not exist at the baseline and is attributable to the task, a visible window that did not exist at the baseline, or a print job of her account. A new process is *not* hers when its parent, or that parent's parent, is a program that was already running before the task and is neither the worker's own launch chain nor the Windows shell: the helper processes a pre-existing browser or chat client spawns for itself are that program's business (`task_started_processes` in `clara/portal_windows.py`). A process whose parent cannot be read, has exited, or lives outside the session stays attributed to the task, so nothing Clara launched is waved through once its launcher is gone. New windows are always reviewed, even inside a pre-existing program, because Clara may have opened them.
- A successful T1 TaxPrep preparation result for this exact attempt has an acknowledged portal receipt. General desktop tasks and interrupted/failed tasks still require review.
- Two clear observations are separated by at least three seconds. Any activity or incomplete observation resets that settling interval.
- The existing executor, tool, external-operation and attachment checks are also clear, and the portal returns its release receipt. Windows observations cannot clear another unresolved operation.

The model gets one cleanup reminder with newly observed application windows. It must verify saved outputs/uploads and close the windows it opened with normal close controls. Programs other people had open before the task are left alone unless one blocked the work, and unsaved work that is not Clara's is never discarded. The observer never closes applications, kills task processes, discards unsaved work or interprets a vanished window as proof of an upload. Remote record and output verification remain separate requirements.

An unreadable session/printer, a still-running browser or application that the task started, a changed controller after restart, or an incomplete task remains held. This is an observational handoff for the supported dedicated T1 workflow, not a sandbox or proof about arbitrary scheduled commands, Windows services or unknown application integrations. Do not qualify new workflows by reusing this flag without testing their external activities.

## Local configuration

In the existing protocol-v1 portal.json, add:

```json
"windows_handoff": {
  "exclusive_session": true,
  "qualified": false
}
```

Keep `enabled: false` during deployment/setup. On an enabled portal worker, `exclusive_session` enables baseline capture and diagnostics; `qualified: false` keeps the automatic release gate closed. After native observations and a test task's cleanup have been reviewed, qualification can be enabled for the supervised two-task acceptance test below. Keep it enabled for general staff use only after that test passes. Changes require a Clara restart. Existing local-only conversations are unaffected. No model tool can change the in-memory qualification flags.

With qualification enabled, an unavailable desktop or pending printing of Clara's account fails the task before any model query or application action. Programs already open in the account do not block it; Clara may close one that stands in the way of her work. Staff should use the portal on their own computers, leaving the dedicated worker desktop for Clara. Chrome's separate profile retains website sign-in storage when its task window closes.

## Releasing a completed test after operator review

Starting Clara opens its local dashboard and starts the configured outbound portal worker. The local URL is normal; it does not mean the portal worker is available. A saved recovery hold blocks new claims, and the portal's execution setting must separately be enabled. A held or claim-unknown worker sends an idle `busy: false` heartbeat at most every `heartbeat_interval_s` (capped at 120 s, default 60 s) so the portal does not label it offline; a rejected or ambiguous first claim is retried every 30 s; unexpected runtime exceptions are logged (redacted) to `<data>/logs/portal-runtime.log`, with the exception class name shown in the local status.

For a **finished T1 already acknowledged as Ready to Email**, `Release-ClaraPortalHold.ps1` provides an explicit operator review path. Stop the idle Clara process first; inspect the saved delivery and current dedicated desktop. Close task applications normally and settle printing. Unrelated or older controllers must be identified before stopping them; the recovery command never kills applications. Supply the exact job, worker, attempt and fence, a substantive inspection note, and `-ConfirmDesktopIdle`. For uncertain PandaDoc reservations, each `-Operation` value binds an operation ID to the verified remote-record evidence ID for its existing delivered packet (`operation-id=evidence-id`). The original business key and remote display title are retained in the review; neither is rewritten to make them match.

The command checks two fresh Windows observations with the same session/controller identity, rejects leftover task applications, controller/model processes, pending printing, incomplete tools and unfinished uploads, saves a local inspection record, and sends only the normal exact-attempt `clara-quiesce` report. Unrelated chat windows and Windows background process changes do not block this explicit completed-task review; the complete observations remain in its audit record. A successful portal release receipt is required before the local cycle is retired. It preserves the original Windows baseline, job result, files, packet links and usage. It never resumes the completed task, enables portal execution, changes worker credentials, or qualifies future automatic handoffs. A rejected or ambiguous request retains the local hold for inspection.

After release, start Clara normally. Its idle claim check should refresh portal presence even when execution is disabled. Review the portal queue before enabling execution; verify a fresh portal chat before assigning another closeout.

## Read-only RDP check

Run Test-ClaraWorker.ps1 from the reviewed source, using the installed desktop Python. It writes a dated worker-check JSON under `%LOCALAPPDATA%\Clara\diagnostics` and prints the exact path. It does not install/update Clara, alter portal settings, request model inference, print a document, click an application or open a port. Only its own read-only probe is stopped if it exceeds twelve seconds.

Review the report for an active/unlocked session, complete process and printer visibility, and unexpected baseline apps. Native Windows CI checks API compatibility with a harmless background process; CI does not qualify an interactive RDP or the TaxPrep/Chrome applications.

## Connected acceptance still required

1. Use test closeouts and a dedicated unlocked account. Configure worker credentials and required providers; keep live clients out of this test. After environment review, enable the worker and portal execution only for this supervised acceptance window. Keep automatic handoff unqualified for the initial task.
2. Run one complete T1 through actual TaxPrep, PandaDoc and OneDrive. Verify the individual documents and signing links, human email draft and Ready to Email result. Confirm normal app cleanup. While qualification is false, the desktop hold is expected; reconcile that exact attempt through the portal after inspecting the observations and outputs.
3. Review the initial task's native observations and normal cleanup, then enable qualification for the controlled queue test and submit two staff tasks. The second must remain queued until the first task's applications/printing settle and the portal confirms release. A failed check means disable qualification and resolve the cause before general staff use.
4. Stop a task during a command/print or upload. Confirm the next task cannot start, incomplete usage remains unknown and existing work is preserved. Continue only through the portal's exact-attempt reconciliation.
5. Interrupt RDP/Clara and restart. Confirm old execution is not replayed and an old baseline/receipt cannot be used as a new attempt's qualification.

## API references

The probe uses [WTS session state](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ne-wtsapi32-wts_connectstate_class), [process enumeration](https://mhammond.github.io/pywin32/win32ts__WTSEnumerateProcesses_meth.html), process creation times, and [EnumJobs](https://learn.microsoft.com/en-us/windows/win32/printdocs/enumjobs). [JOB_INFO_1](https://learn.microsoft.com/en-us/windows/win32/printdocs/job-info-1) explains why a returned/retained print status alone does not establish completed printing.
