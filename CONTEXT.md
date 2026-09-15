# Clara continuation context

Updated: 16 September 2026 (Claude Code takeover session). This is the handover for the existing Clearhouse integration work, including continuation in Claude or another assistant. Read this before older release notes. This file records the last verified state; inspect current state before any action. It is not a claim that a live test or deployment is complete.

For the ready-to-use Claude Code project prompt and detailed Mac/RDP/Lovable instructions, read [CLAUDE-CODE-HANDOFF.md](CLAUDE-CODE-HANDOFF.md). Codex's `continue-clara-working-demo` follow-up was paused for this takeover; Clara's Windows autostart was left unchanged.

## Start here

The immediate objective is to finish the **TEST5 TaxPrep T1 closeout** to a real Ready to Email receipt and confirm the worker takes the next job. TEST3 and TEST4 were cancelled on 15 September (user decision: "leave them or delete them, we will do a new test"); do not recover them. TEST2 remains the manually reassigned Ready to Email item that must not be touched.

Use this repository's **`feat/clearhouse-portal-v1` branch**, not `main`. The integration changes and this handover are on that branch:

```sh
git clone --branch feat/clearhouse-portal-v1 https://github.com/nikitanikist/claraAgnet.git
```

The portal is a separate repository, `nikitanikist/clearform-hub`, branch `main`. Test site: https://testclearhouse.nikist.ai. Portal frontend/backend/database changes must go through Lovable (plan mode, review, one approval). This handover does not authorize direct portal edits. Read-only database diagnosis through the Supabase SQL connector is authorized by the user; `clara_continue_job` and `clara_record_answer` were also invoked through SQL as the assigning super admin when the portal UI could not.

The user has limited assistant and Lovable credit; keep changes focused on observed blockers, no experiments. Distinguish prepared code, pushed code, installed code and verified live behaviour.

## Current source and deployment state

| Surface | Last verified state |
| --- | --- |
| Clara GitHub integration branch | `dbd4b4e6bd826e27eb0b181f310944f12f1d3155` (16 Sep 2026); 386 tests pass |
| Windows installed Clara | `b7eb0bfb182724d87e77d7dc5d57740d2a79796d` (installed 16 Sep ~02:08 IST). `ef167b1` (source-copy re-check by original, finish-check text in the portal reason) and `dbd4b4e` (stage names on checkpoint events) are **pushed, not installed**: the Mac locked and the RDP session dropped before they could be installed |
| Portal database | Lovable migration `20260915190732` (late quiescence reports for cancelled/reviewed attempts are superseded, no re-hold); `clara-quiesce` and `clara-result` redeployed |
| Test frontend | v4.0 published (Review and continue for needs_review, "Held for review" mood). A Lovable build for the Clara workspace redesign ("Clara workspace: live agent experience", plan approved 15 Sep 22:48 UTC) was in progress when this file was written; check `.lovable/plan.md` and the Lovable message list before assuming it landed |
| TEST5 | Portal job `80bb13ae-2506-44a1-b5fd-700945d9abe4` in `needs_review` after attempt 3 (fence 17): all outputs exist and were bound by `record_portal_delivery`; the local finish check still failed on the source-copy hash (fixed in `ef167b1`). Next: install, Review and continue (attempt 4), expect `completed_prepared` and Ready to Email for T Super Admin `69af37fd-…` |

Clara commits pushed on 15/16 September, in order:

- `b3d05fd`…`5db651b`: interrupted-status review of `incomplete` jobs, storage hold review, idle `busy:false` heartbeat while held, claim retry every 30 s, redacted `portal-runtime.log`, canonical reservation triples, sidecar-hash starter-skill refresh. Installed.
- `904a34d`, `6aa4c76`: a held cycle with nothing in flight asks the portal for work again. Installed.
- `0508ade`: `record_portal_delivery` no longer demands the reservation key on the page; exact identity vocabulary in the tool description, task prompt, skill and error messages; 20-minute readback window. Installed.
- `c6a3023`: executor reaper. After any task ends, the desktop Python ends the Claude CLI and its MCP bridges left under the task (applications are never touched) and records an `executors_reaped` event. Installed.
- `b7eb0bf`: review fixes: URL-only spelling tolerance with token boundaries, values may be proven across several fresh Chrome readbacks, `external_key` must equal the canonical key. Installed.
- `ef167b1`: source-copy evidence is re-checked against the untouched original (path + hash recorded at copy time) instead of the TaxPrep working copy; the portal `needs_review_reason` carries the local finish-check sentence. **Not installed.**
- `dbd4b4e`: checkpoint events carry `meta.stage`/`meta.status` and the message `Saved workflow progress: <stage> <status>.` **Not installed.**

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

## TEST5: outputs complete, one code fix away from Ready to Email

Fixture `ZZ TEST 5` (form `00000000-0000-4023-8473-000000000005`, job `80bb13ae-2506-44a1-b5fd-700945d9abe4`, conversation `90364591-84ed-45f7-a965-3230bcd5d364`), assigned by T Super Admin on 15 Sep 19:22 UTC with TEST4's instructions adapted.

- Attempt 1 (fence 15): printing, verification, OneDrive folder `CLARA-TEST5-23473-2025-Erica-Carlos-20260916-0105` and both PandaDoc packets completed in about 22 minutes. It then looped for 11 minutes on `record_portal_delivery` because the canonical reservation key never appears on a page (fixed in `0508ade`/`b7eb0bf`). The user stopped it; the stop left the Claude CLI, node and python bridge processes alive, which the observer reported as in-flight for ever (fixed in `c6a3023`; 14 leaked `claude.exe` from earlier runs were also killed by hand).
- Attempt 2 (fence 16): asked "Continue with incomplete usage information?" (answered through `clara_record_answer`), then failed within 20 seconds: the server's native Claude login had hit its 5-hour session limit ("resets 4am Asia/Kolkata"). Clara has no API fallback; a heavy day can stall the worker for hours. Discuss the plan or an API key fallback with the user.
- Attempt 3 (fence 17, after the limit reset): recorded delivery on the first call, saved the signature, delivery and review checkpoints, published the handoff and reported. The local finish check still returned incomplete because it re-hashed the source-copy evidence against the TaxPrep working copy (the same as TEST4's first blocker); the portal therefore shows `needs_review` with a generic reason and the form is still `pending`. `ef167b1` fixes both the check and the reason text.

Recovery path: install `dbd4b4e` at idle, post a short reuse message in the conversation, run Review and continue (or `clara_continue_job` with every unknown resolved, as done for attempts 1 and 2), and let attempt 4 finish. Expected result: outcome `completed_prepared`, form `ready_to_email` assigned to T Super Admin, three manifest artifacts (two PandaDoc, one OneDrive folder). Outputs and reservations must not be recreated.

## TEST3 and TEST4: cancelled

Both were cancelled on 15 Sep 19:02–19:04 UTC after the user chose a fresh test over recovery. Their outputs (TEST4 folder and packets, TEST3 PDFs and draft) still exist remotely and locally; leave them.

## Why the failures and delays happened

The observed problems are mostly workflow/tool/integration defects, not evidence that a weaker model was selected:

- Save As was visibly present while a text detector missed it and waited about two minutes.
- PandaDoc checks used a guessed route/frame and long polling; historical instructions incorrectly insisted the T183 signature was on page two when Part F was on page one.
- Synthetic drag actions misplaced fields. Current guidance requires supported drag/native pointer actions and a visual check against the actual signature line.
- The SDK transport buffer was too small for a large tool message.
- Completion evidence, remote-operation identity and portal handoff/release rules did not fit together reliably. The current editable-copy proof and reservation-key mismatch are concrete examples.
- `record_portal_delivery` demanded the reservation key in page text; PandaDoc and OneDrive never show it, so the model re-read pages for ten minutes. Rejections now name the exact identities and the missing value.
- A portal stop cancelled the SDK task but the Claude CLI subprocess tree survived; the observer reported it as unfinished execution and the portal refused every continuation. The worker now reaps its own executors after each task.
- The finish check re-hashed the TaxPrep working copy, which the application rewrites; it now checks the untouched original.
- A held worker did not refresh idle claim presence, so the portal could say **offline** while the local server was still running. Now a held or claim-unknown worker sends an idle `busy: false` heartbeat at most every `heartbeat_interval_s` (capped at 120 s, default 60 s), a rejected or ambiguous first claim is retried every 30 s, and unexpected runtime exceptions are logged (redacted) to `<data>/logs/portal-runtime.log` with the exception class name shown in the local status. Starting another Clara process does not resolve the underlying hold.

The Windows model setting was read as **`opus`**, with medium reasoning configured. The exact resolved Claude model version was not captured. Do not invent a version or claim changing the model will fix these state/verification defects.

## Server state and access

Windows application: `%LOCALAPPDATA%\ClaraAgent`.

Windows persistent data: `%LOCALAPPDATA%\Clara`, including `clara.sqlite3`, skills, configuration, logs, workspace outputs and dedicated browser state. Backups remain under `%LOCALAPPDATA%\ClaraBackups`.

The last check (16 Sep 02:09 IST) found the local listener running at `127.0.0.1:8876` on revision `b7eb0bf` as a single `python` process, with no stray `claude`/`node` executors; the worker cycle was held for TEST5 review. Do not infer a current process ID from an old observation. Native model login and encrypted portal worker credentials are already configured in the dedicated account; preserve them. Do not create a new runner or request a new key without a demonstrated need.

The native Claude login is a subscription session with a 5-hour usage window. On 15 Sep it ran out during TEST5 ("You've hit your session limit · resets 4am Asia/Kolkata") and the running attempt failed within seconds. Clara has no API-key fallback (`fallback_model=None`); raise this with the user before relying on Clara for a full working day.

Server access from the Mac goes through the Windows App session "Clearhouse Clara.agent". When the Mac locks, that session window disappears and both the RDP typing route and the app-window screenshots stop working until the Mac is unlocked and the session reopened; the Windows desktop session itself must stay signed in for Clara's desktop work. Typing lessons: per-key `key` actions work, `_ ? > + /` cannot be typed (use wildcards, `[char]95`, `-join`, `Where-Object`, backslashes), never press Escape (it leaves full screen). Do not type into the session while Clara is doing desktop work; observe with window screenshots only. A maximized PowerShell window (Windows Terminal tab 2) was left open on the desktop; minimize or close it at idle.

Autostart is already implemented and registered using `Set-ClaraAutostart.ps1` and `Run-ClaraAutomatic.ps1`. It uses the Windows account identity, includes restart behavior and a roaming-profile Startup hook, and does not hard-code the RDP hostname. It still requires a usable signed-in desktop. Portal login cannot start/unlock Windows. Dynamic-host and disconnect behavior are not fully qualified.

GitHub carries source, committed skills and this sanitized context. It does **not** carry runtime SQLite, client PDFs, output links, encrypted worker keys, browser sessions or native Claude credentials. A cloud checkout alone does not grant RDP access. Use the already authorized computer tools/session if available; if unavailable, report the specific access gap rather than pretending to have inspected Windows.

Discover exact job IDs, attempts, fences, source paths, output folders and signing links from the existing TEST3/TEST4 conversations and local bindings/evidence. Do not post them in a public repository. For read-only database diagnosis, use a SQLite `mode=ro` connection; constructing a normal Store may initialize/migrate data.

On the original Mac, detailed private notes are at `~/Downloads/Clearhouse-Lovable-Review/TaxPrep-Fast-Path-Test-Run.md`, with targeted screenshots and `portal-return-current.txt` alongside it. Those are local references, not prerequisites for a new cloud checkout. The Codex automation `continue-clara-working-demo` previously ran every 15 minutes and was paused for the Claude takeover. Verify if that state has since changed; do not create a second scheduler or competing desktop controller.

## Next actions, in order

1. Unlock the Mac, reopen the Windows App session "Clearhouse Clara.agent", and install `dbd4b4e` at idle: `.\Set-ClaraAutostart.ps1 -Disable`, `Stop-ScheduledTask -TaskName Clara-S-1-5-21-1046630959-3975722937-3647023733-1650`, stop the Clara python process, `.\Update-ClaraPortalTest.ps1 -Revision dbd4b4e6bd826e27eb0b181f310944f12f1d3155`, `.\Set-ClaraAutostart.ps1 -Start`, then check `%LOCALAPPDATA%\Clara\logs\automatic-start.log` and that exactly one `python` and no stray `claude`/`node` processes run.
2. Post a short reuse message in the TEST5 conversation (outputs exist, do not recreate, record delivery and finish), then Review and continue. Watch `clara_events`; attempt 4 should end within a few minutes with `completed_prepared`.
3. Verify the Ready to Email receipt: form `ready_to_email`, `assigned_to` = T Super Admin, manifest with the OneDrive folder and both PandaDoc links, no email sent. Confirm the worker returns to idle without a hold and claims the next job.
4. Review the Lovable redesign build (tests, preview at 2560 and 375 px, publish) and report to the user; do not start new Lovable work without a plan-mode round.
5. Keep this file, `CLAUDE-CODE-HANDOFF.md` and memory current with installed revisions and verified behaviour.

Deferred: ProFile, extra workers, unrelated feature expansion. Do not invent completion-time estimates.

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
| Windows observations / startup / executor reaper | `clara/portal_windows.py`, `clara/windows_activity.py`, `clara/windows_reap.py`, `Set-ClaraAutostart.ps1`, `Run-ClaraAutomatic.ps1` |
| Effective skill installation | `clara/config.py`, `clara/skill_pack.py`, `clara/starter_skills/taxprep-fast-path/SKILL.md` |
| Portal owner implementation (other repo) | `supabase/functions/_shared/claraServer.ts`, `claraHandoff.ts`; deployed entrypoints `clara-result`, `clara-handoff-retry` |

Prior validation, not a fresh rerun:

- Nine focused tests passed for SDK buffer/navigation work; the buffer test reproduces the 1 MiB failure and success with a larger bounded limit.
- 52 focused Windows/runtime tests passed for restart observation changes.
- 15 tests passed for owner guidance: `.venv/bin/python -m pytest tests/test_portal_intake.py tests/test_portal_results.py tests/test_portal_outputs.py -q`.
- Portal owner change: Lovable reported 92 checks passed and both affected entrypoints deployed; implementation diff was independently reviewed.
- Source snapshot guidance: documentation/skill diff checked; no new live run or duplicated suite for that prose-only change.

These results do not establish completed end-to-end acceptance. Older README/runbooks include earlier unconnected-release status, generic `main` update commands and fixed-Laureen language. For this active integration, use this handover's current decisions and verify the actual code/live state.
