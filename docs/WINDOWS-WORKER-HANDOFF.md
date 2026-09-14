# Dedicated Windows worker handoff

Development implementation; the real Clearhouse RDP is not yet qualified. The user confirmed on 2026-09-15 that the Windows account clara.agent will be dedicated to Clara.

## What is implemented

Before a portal model task starts, Clara saves a read-only baseline from the separate desktop Python. It records the Windows account/session, boot and controller process identity, current account processes with creation times, visible window handles/classes, and current account print jobs. It omits document titles, command lines, printer names, credentials and client paths. The baseline is tied to the local job and is never replaced during recovery.

After result reporting, WindowsHandoff takes fresh observations. Automatic release requires all of the following:

- The configured session is dedicated and has passed Windows qualification.
- The baseline was complete, interactive and clear of existing application windows, hidden TaxPrep/Chrome/Office instances and pending printing. Clara's startup console and Windows shell can stay open.
- The same Windows account, session, boot and controller process remain. A reused PID with a different creation time is a different process.
- Every new current-account process and visible window has gone, and all configured queues were readable with no remaining current-account print job. Paused, retained or failed print jobs are not treated as finished.
- A successful T1 TaxPrep preparation result for this exact attempt has an acknowledged portal receipt. General desktop tasks and interrupted/failed tasks still require review.
- Two clear observations are separated by at least three seconds. Any activity or incomplete observation resets that settling interval.
- The existing executor, tool, external-operation and attachment checks are also clear, and the portal returns its release receipt. Windows observations cannot clear another unresolved operation.

The model gets one cleanup reminder with newly observed application windows. It must verify saved outputs/uploads and use normal close controls only for task-owned windows. The observer never closes applications, kills task processes, discards unsaved work or interprets a vanished window as proof of an upload. Remote record and output verification remain separate requirements.

An unreadable session/printer, still-running browser or application, changed controller after restart, or incomplete task remains held. This is an observational handoff for the supported dedicated T1 workflow, not a sandbox or proof about arbitrary scheduled commands, Windows services or unknown application integrations. Do not qualify new workflows by reusing this flag without testing their external activities.

## Local configuration

In the existing protocol-v1 portal.json, add:

```json
"windows_handoff": {
  "exclusive_session": true,
  "qualified": false
}
```

Keep `enabled: false` during deployment/setup. On an enabled portal worker, `exclusive_session` enables baseline capture and diagnostics; `qualified: false` keeps the automatic release gate closed. After native observations and a test task's cleanup have been reviewed, qualification can be enabled for the supervised two-task acceptance test below. Keep it enabled for general staff use only after that test passes. Changes require a Clara restart. Existing local-only conversations are unaffected. No model tool can change the in-memory qualification flags.

With qualification enabled, an unavailable/dirty initial desktop fails before any model query or application action. Close task applications before the first queued run. Staff should use the portal on their own computers, leaving the dedicated worker desktop for Clara. Chrome's separate profile retains website sign-in storage when its task window closes.

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
