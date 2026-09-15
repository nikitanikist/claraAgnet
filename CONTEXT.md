# Clara continuation context

Updated: 15 September 2026. This is the handover for the existing Clearhouse integration work, including continuation in Claude or another assistant. Read this before older release notes. This file records the last verified state; inspect current state before any action. It is not a claim that a live test or deployment is complete.

## Start here

The immediate objective is to finish the **existing TEST3 and TEST4 TaxPrep T1 closeouts**, using Clara to perform the work, and verify the portal handoff and availability for the next job. Do not create replacement test closeouts, restart all printing, or begin a UI redesign. TEST4 has finished document preparation but is blocked before Ready to Email. TEST3 is queued.

Use this repository's **`feat/clearhouse-portal-v1` branch**, not `main`. The integration changes and this handover are on that branch:

```sh
git clone --branch feat/clearhouse-portal-v1 https://github.com/nikitanikist/claraAgnet.git
```

The portal is a separate repository, `nikitanikist/clearform-hub`, branch `main`. Test site: https://testclearhouse.nikist.ai. Portal frontend/backend/database changes must go through Lovable. This handover does not authorize direct portal edits.

The user has limited remaining assistant allowance and wants a working demo quickly. Keep changes focused on observed blockers. Give brief, honest progress updates; distinguish prepared code, pushed code, installed code, and verified live behavior. Avoid repeating passed tests without a new reason. Do not use Lovable credits for routine testing or cosmetic changes.

## Current source and deployment state

| Surface | Last verified state |
| --- | --- |
| Clara GitHub integration branch | `805083821c93d63485a862ef9552acfd9a39a70d` before this documentation commit; local source and remote matched, with a clean checkout |
| Windows installed Clara | `25c7679535ab90b082d64ba0c6e76677000427a5`; later owner guidance and source-copy guidance are **not yet installed** |
| Portal GitHub `main` | `f9edae8` — corrected Ready to Email owner selection |
| Portal backend deployment | Lovable reported `clara-result` and `clara-handoff-retry` deployed, with 92 checks passed; code diff independently reviewed, suite not independently rerun |
| Test frontend | v3.9 published; existing Review and continue UI available |
| Actual next owner handoff | Still unverified: TEST4 has not reached a successful handoff after the owner fix |

Relevant Clara commits already pushed:

- `3d798a3307f69d786ea84d7663ad577bbe02d270`: bounded SDK message buffer raised from 1 MiB to 16 MiB; TaxPrep visible-dialog and PandaDoc/Part F navigation corrections. Installed.
- `25c7679535ab90b082d64ba0c6e76677000427a5`: stopped/failed task desktop observations can be reviewed while genuine executors and print jobs remain blocking. Installed.
- `f06e8a8b261792982213831bbdfb428bed67bedd`: Ready to Email assignment-owner guidance in intake, results, output instructions and skills. **Not installed.**
- `805083821c93d63485a862ef9552acfd9a39a70d`: preserve an untouched TaxPrep snapshot as source evidence, separate from the editable live copy. **Not installed.**

The next assistant must check for later commits and live changes instead of assuming these revisions remain current. Do not use generic older update instructions that pull `main` for this integration worker.

## User decisions that govern this work

- Initial closeout scope is **T1 in TaxPrep**. ProFile is future work. T2/T3 are not enabled closeout workflows.
- One dedicated Windows worker, one desktop task at a time. Other requests wait. RDP host names can change; the account/profile and C:/O: paths persist. Do not hard-code a server name or add another worker.
- **Ready to Email returns to the exact staff account that originally assigned the closeout to Clara.** Amit's assignment returns to Amit; an assigning super admin's returns to that super admin. A later reviewer/continuation actor, form creator, worker identity, OneDrive account or fixed reviewer setting must not replace that identity.
- Laureen handles **invoicing only**; she is not the default Ready to Email owner. Older instructions naming her as the universal recipient are superseded.
- The user already manually reassigned an older Ready to Email item to Test Agent. **Do not search for it, alter it, or undo that reassignment.** Preserve earlier completed tests.
- PDFs go to **OneDrive**. The portal gets the OneDrive folder link and each member's PandaDoc signing link, plus the prepared email draft. Do not upload closeout PDFs to the portal. A separately requested file attachment in ordinary chat is a different workflow.
- Clara stops at Ready to Email. No client email, SMS, signing invitation/reminder, actual signature, or tax filing. Preparing signature fields/packets and collecting signing links is within the test scope. Staff perform review and sending.
- Ordinary chat/system requests must not acquire a Ready to Email closeout status. There is existing distinct general-request completion logic; verify live behavior before claiming this fully resolved.
- Preserve originals, saved PDFs, drafts, remote folders, job history and evidence. Recovery must reuse existing output and identify the first unfinished step.
- User authorizes operating the existing Windows App/RDP session, commands, focused Clara fixes and these tests. Do not repeatedly ask the user to run commands already within that scope.
- Server-to-Mac clipboard/file export is not allowed directly. If a transfer is necessary, the user authorized the existing WhatsApp **Clear House Agent project** group and native Mac WhatsApp route. Do not send secrets or client documents to GitHub.
- Uploaded transcripts/maps are reference material. The improved TaxPrep map/guide takes precedence over errors in the older transcript. Actual visible form layout takes precedence over a historical fixed page number.

## TEST4: output completed, final handoff blocked

Last portal state: **Needs review**. Last local job state: **`incomplete`**. The outbound worker cycle is held. The most recent accepted portal result is `needs_review`, with `handoff.attempted=false`; this is not a successful Ready to Email receipt.

Clara's run and subsequent observations established:

- Six final PDFs: two client returns, two T183s and two engagement letters.
- Client copies have 80 and 47 pages after removing the respective internal Note Summary page; T183s have two pages each; engagement letters one each. Keep raw prints separately.
- All six uploaded to the TEST4 OneDrive folder; remote names/sizes matched the local output manifest.
- Two PandaDoc packets and signing links created for the assigned test recipients. Part F and engagement-letter signature/date fields were placed. An initial misplaced field was corrected; an accidental signing dialog was cancelled. Nothing was signed or emailed.
- The former SDK message-size crash did not recur in this run. Some unnecessary waits and field-placement correction remained; speed is not yet consistently qualified.

### Confirmed blocker 1: source evidence points at an editable copy

Exact terminal message:

> Workflow incomplete. Evidence for source-copy no longer matches: An evidenced file changed or disappeared. Re-verify it before advancing.

Read-only inspection found both copies still present under the TEST4 job's output directory:

- `working/live/<test-return>.125`: the evidence target, opened in TaxPrep; its current hash differs from the saved proof.
- `working/<test-return>.125`: the preserved snapshot; its current hash still matches the original proof.

No file was restored or edited during diagnosis. The reason for the live file's byte change has not been pinpointed. Do not claim it was only metadata or that its tax contents are unchanged. Clara reported the original O: source unchanged; the later independent check verified the local preserved snapshot, not O: again.

The workflow incorrectly used the mutable live copy as enduring source proof. Commit `8050838` corrects future guidance. It does **not** retroactively repair this existing run. Re-verify the preserved snapshot and establish valid evidence in an authorized continuation; do not rewrite the old hash or waive the check.

### Confirmed blocker 2: three external operations remain unresolved

There are three uncertain reservations: one storage operation and two PandaDoc packet operations. Existing outputs were verified, but reservation business keys differ from the keys used in the remote-record evidence. `Operations.reconcile` requires matching `system` and exact `external_key`, as well as sufficiently fresh evidence.

Resolve the existing identities with evidence and an auditable mapping. Do not mark them absent, fabricate confirmation, or create replacement folders/packets. These reservations independently keep the worker held even after source evidence is corrected.

### Recovery limitations already investigated

- A confident final model narrative does not override `finish_check` or the actual receipt.
- The accepted TEST4 result is already `needs_review` with no deliverable artifacts in that accepted result. Result reporting is immutable/idempotent for that local job. Do not replace its journal payload or alter job status to pretend it was completed.
- `Finish-ClaraPortalReport.ps1` is for a qualifying saved result, not for replacing this already accepted incomplete result.
- `Release-ClaraPortalHold.ps1` currently supports a finished T1 already acknowledged Ready to Email. Its external-operation review handles PandaDoc, not this unresolved storage case. It is not a direct solution for TEST4's current state.
- Prefer the existing **Review and continue** flow. It preserves job/conversation history but creates a **new attempt/fence**. Read exact current identities; never reuse an old attempt's authority.
- `portal_windows.py` currently classifies failed/stopped/interrupted/cancelled attempts for interrupted review; `incomplete` is not in that set. Inspect the actual current dialog/report first. This is a possible next obstacle, not a confirmed reason to patch preemptively.

## TEST3: queued, preserve earlier work

The first execution failed after six verified PDFs and an unfinished PandaDoc draft, when a Claude SDK JSON message exceeded 1 MiB. Local workflow checkpoints survived. The exact oversized payload was not retained, so it was not proven to be a screenshot alone.

The buffer/navigation update was installed. The old attempt was reviewed through the portal, a real continuation message requiring reuse was sent, and Review and continue accepted. TEST4 was older in the queue and ran first; TEST3 remains queued behind the held worker.

Reuse the existing TEST3 PDFs and unfinished draft. Discover its current attempt/fence in the portal/runtime before doing anything. Do not reorder the queue. If continuing TEST4 gives it a newer queue time, TEST3 may run first; that is expected with oldest-first scheduling.

## Why the failures and delays happened

The observed problems are mostly workflow/tool/integration defects, not evidence that a weaker model was selected:

- Save As was visibly present while a text detector missed it and waited about two minutes.
- PandaDoc checks used a guessed route/frame and long polling; historical instructions incorrectly insisted the T183 signature was on page two when Part F was on page one.
- Synthetic drag actions misplaced fields. Current guidance requires supported drag/native pointer actions and a visual check against the actual signature line.
- The SDK transport buffer was too small for a large tool message.
- Completion evidence, remote-operation identity and portal handoff/release rules did not fit together reliably. The current editable-copy proof and reservation-key mismatch are concrete examples.
- A held worker does not currently refresh idle claim presence, so the portal can say **offline** while the local server is still running. Starting another Clara process does not resolve the underlying hold.

The Windows model setting was read as **`opus`**, with medium reasoning configured. The exact resolved Claude model version was not captured. Do not invent a version or claim changing the model will fix these state/verification defects.

## Server state and access

Windows application: `%LOCALAPPDATA%\ClaraAgent`.

Windows persistent data: `%LOCALAPPDATA%\Clara`, including `clara.sqlite3`, skills, configuration, logs, workspace outputs and dedicated browser state. Backups remain under `%LOCALAPPDATA%\ClaraBackups`.

The last check found the local listener running at `127.0.0.1:8876` while the worker cycle was held. Do not infer a current process ID from an old observation. Native model login and encrypted portal worker credentials are already configured in the dedicated account; preserve them. Do not create a new runner or request a new key without a demonstrated need.

Autostart is already implemented and registered using `Set-ClaraAutostart.ps1` and `Run-ClaraAutomatic.ps1`. It uses the Windows account identity, includes restart behavior and a roaming-profile Startup hook, and does not hard-code the RDP hostname. It still requires a usable signed-in desktop. Portal login cannot start/unlock Windows. Dynamic-host and disconnect behavior are not fully qualified.

GitHub carries source, committed skills and this sanitized context. It does **not** carry runtime SQLite, client PDFs, output links, encrypted worker keys, browser sessions or native Claude credentials. A cloud checkout alone does not grant RDP access. Use the already authorized computer tools/session if available; if unavailable, report the specific access gap rather than pretending to have inspected Windows.

Discover exact job IDs, attempts, fences, source paths, output folders and signing links from the existing TEST3/TEST4 conversations and local bindings/evidence. Do not post them in a public repository. For read-only database diagnosis, use a SQLite `mode=ro` connection; constructing a normal Store may initialize/migrate data.

On the original Mac, detailed private notes are at `~/Downloads/Clearhouse-Lovable-Review/TaxPrep-Fast-Path-Test-Run.md`, with targeted screenshots and `portal-return-current.txt` alongside it. Those are local references, not prerequisites for a new cloud checkout. The original automation `continue-clara-working-demo` was active every 15 minutes; coordinate/pause overlapping work if another assistant takes over. Do not create a second scheduler or competing desktop controller.

## Next actions, in order

1. Read current user messages, this file, Git revisions and existing TEST3/TEST4 states. Confirm no other assistant/worker executor is actively operating the desktop.
2. Inspect TEST4's existing Review and continue requirements and fresh desktop report. Retain the current result, original baseline and all outputs; do not force-release locks or alter queue rows.
3. Install the reviewed Clara source updates when the executor is idle. Pause autostart during maintenance, stop only the identified Clara service, make the normal local backup, and use the explicitly reviewed integration revision. See `Update-ClaraPortalTest.ps1`; do not accidentally pull `main`.
4. **Verify effective installed skills too.** `Config.initialize` copies starter skills only when absent, and managed skill updates preserve user edits. A Git update alone may leave an older data-folder skill in use. Compare the installed `taxprep-fast-path` and delivery guidance with source, preserve custom content, and apply the relevant corrections deliberately.
5. Resolve TEST4 source proof and the three existing operation identities using the narrowest supported recovery. If a code gap is confirmed, fix that specific gap and test it; do not create a new generic recovery framework. Continue through the existing portal mechanism with the actual new attempt/fence and reuse instructions in the conversation.
6. Let Clara complete existing work in actual queue order. Preserve TEST3's earlier PDFs/draft and TEST4's completed remote outputs. No duplicate test assignments.
7. Verify a real Ready to Email receipt and the assigning staff member's queue, OneDrive folder, per-member PandaDoc links and prepared draft. No actual sending. Verify normal chat stays distinct from closeouts.
8. Confirm the worker becomes available and starts the next queued job, with honest online/busy/held behavior. Report each test separately. Both tests are not complete until these observed outcomes pass.

Deferred: cosmetic UI cleanup, skill-management portal screens, ProFile, extra workers and unrelated feature expansion. No reliable completion-time estimate has been established; do not invent one.

## Lovable workflow

The project is **clearform-hub / ClearForm Hub**. User authorizes the assistant to review and approve plans without asking the user to click normal approval.

Use the callable Lovable connector if available. In the previous session no callable Lovable tools were exposed, despite the user's installed plugin; the authorized native Chrome Lovable interface was used instead. Discover current availability before assuming either condition persists.

Required sequence: Plan mode request -> read complete plan -> give corrections in Plan mode -> read the revised final plan -> approve once -> confirm build acceptance -> inspect landed code/deployment. Do not approve while also introducing unreviewed corrections. With a connector, inspect nested response status; a queued response with `queue_paused=true` and `queue_pause_reason=hitl_tool` is a real tool-approval block. Do not treat an ordinary plan pause as requiring the user to click.

The owner fix already went through this process. It uses original `clara_jobs.created_by`, with validated captured original `authority.assigned_by` fallback only when missing; mismatch fails. Later review/continuation actors are ignored. Already committed handoffs preserve manual reassignment. No DB migration or new frontend publication was required for this backend fix. Do not rebuild it.

## Code map and validation already performed

| Area | Files |
| --- | --- |
| Portal intake / assignment identity | `clara/portal_intake.py`, `clara/portal_bindings.py` |
| Worker / held cycles / reporting | `clara/portal_runtime.py`, `clara/portal_journal.py`, `clara/portal_results.py`, `clara/portal_quiescence.py` |
| Evidence / workflow completion | `clara/evidence.py`, `clara/workflows.py`, `clara/portal_delivery.py`, `clara/portal_outputs.py` |
| External reservation reconciliation | `clara/operations.py`, `clara/portal_hold_review.py` |
| Windows observations / startup | `clara/portal_windows.py`, `clara/windows_activity.py`, `Set-ClaraAutostart.ps1`, `Run-ClaraAutomatic.ps1` |
| Effective skill installation | `clara/config.py`, `clara/skill_pack.py`, `clara/starter_skills/taxprep-fast-path/SKILL.md` |
| Portal owner implementation (other repo) | `supabase/functions/_shared/claraServer.ts`, `claraHandoff.ts`; deployed entrypoints `clara-result`, `clara-handoff-retry` |

Prior validation, not a fresh rerun:

- Nine focused tests passed for SDK buffer/navigation work; the buffer test reproduces the 1 MiB failure and success with a larger bounded limit.
- 52 focused Windows/runtime tests passed for restart observation changes.
- 15 tests passed for owner guidance: `.venv/bin/python -m pytest tests/test_portal_intake.py tests/test_portal_results.py tests/test_portal_outputs.py -q`.
- Portal owner change: Lovable reported 92 checks passed and both affected entrypoints deployed; implementation diff was independently reviewed.
- Source snapshot guidance: documentation/skill diff checked; no new live run or duplicated suite for that prose-only change.

These results do not establish completed end-to-end acceptance. Older README/runbooks include earlier unconnected-release status, generic `main` update commands and fixed-Laureen language. For this active integration, use this handover's current decisions and verify the actual code/live state.
