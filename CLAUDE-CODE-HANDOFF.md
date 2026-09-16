# Claude Code takeover prompt — Clara / Clearhouse

Use the following as my project instructions and initial task. Continue the existing implementation and tests from the recorded state. Read the linked context and inspect current state before operating the worker. Do not start a replacement project.

## 1. Your assignment

You are taking over Clara, our assistant for Clearhouse's accounting closeout portal. The immediate deliverable is a working, repeatable **T1 TaxPrep closeout through the portal**, with the prepared package left in the assigning staff member's **Ready to Email** queue.

Finish the **existing TEST3 and TEST4**. Use Clara itself to perform the workflow so that the result proves the integration works. You may diagnose the server, improve Clara's code and skills, install reviewed updates, and operate the existing review/continuation controls. Do not manually do all the accounting application work yourself and describe that as a successful Clara test.

The user has already authorized this continuation and the existing Mac/Windows/RDP access. Take action within that scope without asking the user to repeat commands or setup you can perform. Ask only for a specific missing access capability, login requiring the user, or an unresolved business decision. Credentials must be entered through the proper login UI, not posted into chat.

Keep the work narrow. We have spent too much time on separate fixes without proving the final handoff. Resolve observed blockers, finish the two tests, and demonstrate that the worker can take the next request. Cosmetic improvements come afterward.

## 2. Repositories and reading order

### Clara application — your implementation workspace

- Repository: **https://github.com/nikitanikist/claraAgnet.git**. The spelling `claraAgnet` is intentional.
- Active integration branch: **`feat/clearhouse-portal-v1`**.
- Current context: **https://github.com/nikitanikist/claraAgnet/blob/feat/clearhouse-portal-v1/CONTEXT.md**.
- Agent entrypoints: `AGENTS.md` and `CLAUDE.md` at the repository root.
- This takeover prompt: `CLAUDE-CODE-HANDOFF.md` at the repository root.

For a new checkout:

```sh
git clone --branch feat/clearhouse-portal-v1 https://github.com/nikitanikist/claraAgnet.git
cd claraAgnet
git status --short
git log -6 --oneline
```

On the original Mac, an existing checkout is at `~/Downloads/Clara-Agent`. Inspect it before cloning again or changing branches. Preserve any edits made after this handover. **Do not develop or install from Clara's `main` branch by accident.**

Read `CONTEXT.md` first, then the relevant implementation files. Older README sections describe earlier releases and are not a reliable current deployment checklist. Older instructions that make Laureen the universal reviewer are superseded.

### Clearhouse portal — inspect code, make changes through Lovable

- Repository: **https://github.com/nikitanikist/clearform-hub.git**.
- Branch: **`main`**.
- Access: private repository; use the existing authorized GitHub connection. If access fails, identify the failure without asking the user to paste an access token.
- Original Mac review checkout: `~/Downloads/Clearhouse-Portal-Review`. Its local checked-out HEAD may be older than `origin/main`; inspect the remote-tracking revision after fetching.
- Test portal: **https://testclearhouse.nikist.ai**.
- Clara settings: **https://testclearhouse.nikist.ai/admin/clara/settings**.
- Lovable project: **clearform-hub / ClearForm Hub**.

Lovable owns portal frontend, backend and database changes. Do not edit or deploy portal code directly. Read the repository to understand a bug, then use Lovable for a necessary change under the process below. Do not modify the previously completed item the user manually reassigned.

## 3. How the system works

Staff use the Clearhouse portal's Clara workspace. They can chat with Clara or assign an eligible closeout. The portal stores conversation/job state and queues work for an authenticated outbound worker.

Clara runs in one dedicated Windows account on the RDP environment. The local application uses the Claude Agent SDK, Windows desktop tools and a dedicated Chrome profile to operate TaxPrep, PandaDoc and OneDrive. It records local workflow stages, evidence, remote operations and result receipts, and reports progress/results back to the portal.

The local dashboard at `http://127.0.0.1:8876` is normal. It is not the portal integration itself. The worker can have a working local dashboard while a saved recovery hold prevents new portal jobs. Do not expose that localhost service publicly as a shortcut.

There are distinct concepts: a conversation, a portal job, an execution attempt/fence, and the worker's ability to accept another task. Model execution finishing does not automatically mean the prepared closeout was accepted by the portal or the desktop was released.

## 4. Non-negotiable business behavior

1. Current closeout scope: **T1 + TaxPrep only**. ProFile, T2/T3 and extra RDP workers are future work.
2. Use the assigned closeout's source, year, members, recipients, naming rules and destination. Missing financial details are unknown; do not manufacture zeros or carry details from another test.
3. Work on a separate live copy of the return and retain an untouched source snapshot. Preserve the original O: file and all earlier outputs.
4. Print the required client return, T183 and engagement letter for each assigned member. Apply additional-document requirements only when actually specified for this closeout.
5. Prepare PandaDoc signature/date fields for the intended recipients and collect signing links. **Do not sign, email an invitation, send reminders/SMS, or file returns.**
6. Upload the final PDFs to **OneDrive**. The portal receives the **OneDrive folder link and per-member PandaDoc signing links**, not uploaded closeout PDFs.
7. Use the existing email draft/template and leave the closeout at **Ready to Email**. Do not send the email. Staff review and send it.
8. **Ready to Email belongs to the exact person who originally assigned the closeout to Clara.** Amit -> Amit. Assigning super admin -> that super admin. Do not substitute the form creator, later continuation actor, OneDrive login, worker account or fixed reviewer email.
9. **Laureen handles invoicing.** Clara does not create invoices in this release. Laureen is not the default Ready to Email owner.
10. The user already moved one previous Ready to Email item to Test Agent. Do not find it, undo it or migrate old completed items.
11. Ordinary chat and system requests must stay distinct from closeout jobs; a simple answered question must not be labeled Ready to Email. A separately requested chat file attachment may be returned through chat.
12. One desktop executor at a time. Preserve queue order and existing job histories. Do not create TEST5 or replacement TEST3/TEST4 assignments.

## 5. Use the connected Lovable connector

The user says **Lovable is already connected in Claude**. Discover and use its callable tools for this project. Prefer that connector over driving Lovable through a browser or sending prompts through another model.

The previous Codex session did not expose callable Lovable tools and therefore used the authorized native Chrome interface. That is a fact about the old session, not a reason to ignore the connector in yours. Inspect tool availability and schemas first. If the connector really cannot be called, state the precise problem and use the authorized Lovable UI only as a fallback.

Mandatory process for every necessary portal change:

1. Select the existing ClearForm Hub project/thread. Inspect relevant current code and avoid work already completed.
2. Send a focused request with **`plan_mode: true`**. No implementation yet.
3. Read the complete plan. With connector tools, follow the returned `message_id`/`thread_id` and inspect **nested `response.status`**; the top-level status of the user message may never become terminal.
4. Send corrections in **Plan mode**. Wait for the revised final plan and read it fully. Do not approve a plan while also introducing corrections that have not been incorporated and reviewed.
5. Once satisfied, send one approval/build message with **`plan_mode: false`**, such as: `Plan approved — implement the final revised plan exactly as reviewed.` In the UI, use its normal Approve action.
6. Confirm build acceptance. A connector response of `accepted` means it took; poll to completion and verify the landed commit/deployment. Do not equate accepting a request with finishing the work.
7. A response queued with `queue_paused: true` and `queue_pause_reason: "hitl_tool"` represents a real tool-approval block. Explain that exact condition if user action is needed. An ordinary plan pause does not require the user to open Lovable and click.
8. Review the implementation and the relevant deployment evidence. Publish only the required test surface if the approved change needs it. Do not repeatedly rebuild or republish unchanged code.

Use the actual connector schema, not guessed tool names or unsupported arguments. Do not spend Lovable credits on routine desktop testing, screenshots, general status checks or deferred UI polishing.

## 6. Mac control and the existing Windows RDP

### Access you should look for

The original setup uses the **Windows App** on the user's Mac. The existing connection/window was named **Clearhouse Clara.agent**, and the dedicated Windows account is **`clara.agent`**. Use the existing saved connection and signed-in session. Do not select an unrelated staff RDP.

The underlying host can be RDP1/RDP2/RDP3/etc. The host name is dynamic; the account/profile and C:/O: paths are expected to persist. Do not bind the worker to one machine name or create a new worker just because the host changed. Inspect the existing configured worker identity.

First discover the actual computer-control tools available in Claude Code, such as connected Mac desktop/browser tools. Permission and a GitHub checkout do not themselves provide a desktop transport. If Claude Code is running in a remote cloud environment, confirm it has a bridge to this Mac/RDP before claiming to operate the server. If tools are missing, report the specific missing bridge once and continue useful source review; do not invent observations.

### Method that worked in the previous session

The previous assistant ran shell commands on the Mac and used native AppleScript/System Events plus Swift Accessibility helpers. It focused Windows App and the existing RDP window, inspected screenshots, and typed into an identified idle diagnostic PowerShell terminal. It did not use a new network-exposed remote shell.

Local helpers are in **`~/Downloads/Clearhouse-Lovable-Review/tools`**, on the original Mac, not in the GitHub checkout:

| Helper | Purpose / caution |
| --- | --- |
| `focus-rdp.applescript` | Activate Windows App and raise exactly the saved Clara connection window; rejects the connection picker |
| `rdp-ui.swift` | Inspect the native Windows App connection picker and act only on a uniquely matched connection |
| `clara-review-ui.swift` / `clara-review-ui` | Read/focus the portal workspace and recovery controls in Chrome |
| `lovable-ui.swift` | Native Lovable fallback; use the connected Lovable tools instead when available |
| `paste-clara-prompt.applescript` | Guard the expected portal URL before pasting into Mac Chrome; contains an old window ID that must be checked/updated |
| `mac-display-info.swift` | Inspect current display geometry before screenshot/click actions |

Inspect a helper's source before use. Old window/tab IDs, coordinates and process IDs are stale observations, not universal constants. Rediscover current targets and foreground focus. Use `set -e` when a shell sequence depends on a successful focus step; otherwise a failed focus command could still be followed by typing into the wrong app.

For Mac Chrome controls, an Accessibility `AXPress` returning success sometimes did not activate the React control. Focusing the actual button and sending Return, or Space for a checkbox, worked. Real typing/pasting was needed to update the composer; setting an AX value alone was not proof of submission. Verify the message appears in the correct conversation and the composer clears.

### RDP input lessons

- Inspect the foreground Windows screen before typing. Never type into a terminal or application Clara is currently operating.
- The RDP display sometimes takes several seconds to redraw. Slow, per-character System Events typing with roughly 0.08–0.12 seconds between characters was more reliable than sending a whole command at once. Wait a few seconds and read the entire command before Enter.
- Some long commands lost characters. Validate the actual line on screen rather than assuming the sent text was received.
- Escape cleared the idle PowerShell command line in this setup; Ctrl+U did not. Do not use those keys blindly in another foreground app.
- Inbound RDP clipboard sometimes pasted stale text. Do not rely on it. Low-level CG keyboard injection caused modifier/input problems in this session; do not keep retrying that route.
- A chat popup can steal focus. Preserve unrelated windows and regain the intended target before action. Do not close unrelated apps merely to satisfy a broad busy check.
- If the Mac is locked, native AX inspection can become blank and screenshots can show wallpaper. That does not prove the remote Clara process failed. Do not bypass the lock, restart Clara or cancel a test because the Mac is locked.

### File transfer boundary

The user prohibits copying data directly from the server to the Mac clipboard or exporting files through an alternate route. When a transfer is needed, the authorized route is the existing WhatsApp **Clear House Agent project** group: the logged-in browser inside the server can post the needed file/message, and the native **Mac WhatsApp app** can retrieve it from that same group. Use only that group and only the material needed for this work. Do not post keys or client documents to GitHub.

## 7. Persistent Windows installation

| Item | Location / behavior |
| --- | --- |
| Source/application | `%LOCALAPPDATA%\ClaraAgent` |
| Persistent runtime | `%LOCALAPPDATA%\Clara` |
| Database | `%LOCALAPPDATA%\Clara\clara.sqlite3` |
| Outputs | Under `%LOCALAPPDATA%\Clara\workspace\outputs\<local-job-id>` |
| Local backups | `%LOCALAPPDATA%\ClaraBackups` |
| Local dashboard | `http://127.0.0.1:8876` |
| Automatic startup | Existing `Set-ClaraAutostart.ps1` / `Run-ClaraAutomatic.ps1` registration |

Portal worker credentials are already saved with Windows encryption. Native Claude login and the dedicated browser sessions already exist. Preserve them; a reconnect or source update should not require creating a new runner or copying browser credentials.

Autostart already starts Clara in the signed-in Windows account and retries process exit. It uses account identity and a roaming-profile Startup hook. It cannot power on/unlock Windows. Do not build another scheduler to work around a held job. The current offline banner can arise because a held worker is not refreshing idle claim presence.

When installing code: verify no active executor; pause the **Windows** automatic restart only for maintenance, stop the identified idle Clara service, make its normal backup, install the reviewed integration revision, verify effective skills, then restore startup. Read the existing updater rather than inventing commands. Do not reset/delete the data folder, clear the instance lock manually, overwrite local edits, or restart an active task to install a documentation-only change.

`Config.initialize` refreshes unmodified starter skill installs on start, using the `<skill>/.clara-starter.sha256` sidecar that records the packaged `SKILL.md` Clara last installed. Locally edited skills are preserved and listed in `<data>/skills-update-pending.json` and on startup stderr with reason `locally_edited` (sidecar present, content changed) or `legacy_unknown` (no sidecar, content differs from the package). Managed skill updates preserve local edits too. Therefore a Git update alone does not guarantee that an edited active skill changed: read the pending list, inspect the actual data-folder skill, preserve custom material, and to adopt a packaged update over a local edit replace the file deliberately, after which the sidecar takes over again.

## 8. Exact handover status and failures

The authoritative detailed record is `CONTEXT.md`. These are last verified observations, not fresh checks made by this prompt.

| Surface | State at handover (updated 16 Sep 2026; `CONTEXT.md` has the detail) |
| --- | --- |
| Clara integration source | `f60ba9e` on `feat/clearhouse-portal-v1`; 422 tests pass |
| Windows installed code | `8019e47` (16 Sep 06:36 UTC); `windows_handoff.qualified: true` since 06:38 UTC (automatic release on). `f60ba9e` (live desktop preview) pushed, awaiting install |
| Portal database | Lovable migration `20260915190732`: late quiescence reports for cancelled or reviewed attempts are superseded and never re-hold the worker |
| Test frontend | v4.1 published (Clara workspace redesign, Lovable commit `f8a61b4f`); 4 pre-existing security-scan findings remain in Lovable's Security view |
| TEST5 | **Ready to Email** (attempt 6, 16 Sep 05:42 UTC) for T Super Admin, no email sent; the post-completion hold was released with `Release-ClaraPortalHold.ps1` after the leftover rule changed (programs open before a task are never Clara's leftovers); worker idle, no hold |
| TEST3 / TEST4 | Cancelled on 15 Sep by user decision; outputs preserved, do not recover |

### TEST4 confirmed blockers

**Source-copy evidence mismatch.** The final check reports: `Workflow incomplete. Evidence for source-copy no longer matches: An evidenced file changed or disappeared. Re-verify it before advancing.` Both files exist. The preserved snapshot still matches the old hash; the live copy opened by TaxPrep does not. We have not proved why the live bytes changed. Do not dismiss it as metadata or change the stored hash to force completion. New guidance keeps evidence on an untouched snapshot and uses a separate live copy. The existing run still needs honest recovery with valid evidence.

**Three unresolved external reservations.** One OneDrive/storage operation and two PandaDoc operations have reservation keys that differ from their remote-record evidence keys. Outputs exist and were verified, but the reconciliation requires exact identity. Resolve these existing identities with an auditable record. Never mark existing output absent, manufacture evidence or create duplicate folders/packets.

The accepted TEST4 result is already `needs_review`, with handoff not attempted. Do not replace its immutable result journal or edit job status. `Finish-ClaraPortalReport.ps1` is not a shortcut to replace an accepted incomplete result. The existing completed-handoff release helper requires an acknowledged Ready to Email result and does not cover the current storage mismatch.

Use the existing review/continuation path once actual requirements are met. Continuation preserves job/conversation history but creates a **new attempt/fence**. The `incomplete` state is not in the current interrupted desktop-review classification; inspect whether that actually blocks this run before making another code change.

### TEST3 and queue order

TEST3 originally failed after printing six verified PDFs and creating an unfinished PandaDoc draft, due to the SDK's 1 MiB message limit. The bounded larger buffer was installed. Existing Review and continue accepted; TEST4 ran first because it was older in the queue. Reuse TEST3's files and draft. If TEST4 is requeued later, TEST3 may run first. Do not modify timestamps or queue order.

### Improvements already made

The configured model alias was **`opus`**, with medium reasoning; the exact resolved model version was not captured. Observed failures were in guidance, waits, tool transport and completion/recovery integration. Do not promise that changing models will fix them.

- Exact TaxPrep LW/T183/ECL selection, Ctrl+R/Ctrl+P, batching by form across members, and visible-dialog fallback were added.
- A visible Save As missed by text detection previously caused a wait of about two minutes.
- PandaDoc route/frame checks previously used incorrect assumptions and long evaluation loops.
- Older instructions wrongly put Part F on page two. On the observed form it is on page one. Current visible signature/date lines govern.
- Synthetic drag actions misplaced fields; use supported drag/native actions and verify placement.
- SDK transport buffer increased from 1 MiB to a bounded 16 MiB. The former crash did not recur in TEST4.
- Owner guidance changed from fixed Laureen to the original assigning staff member; its portal deployment is done, but the next real handoff still needs verification.

## 9. Your first work sequence

1. Read `CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`, this prompt, and any newer user instruction. Inspect current branch/remote revisions and report a short understanding of the remaining work.
2. Check callable Lovable and Mac/browser tools. Use the existing connection. If the original Mac is available, read its detailed private notes described below.
3. Confirm no competing assistant is controlling the desktop. Codex's `continue-clara-working-demo` follow-up was paused for this takeover; verify if state has changed. This is separate from Clara's Windows autostart, which was not disabled by the handover.
4. Inspect current TEST3/TEST4 state, worker cycle, actual attempt/fence, evidence and current Windows activity. For read-only SQLite inspection, use `mode=ro`; normal Store initialization can write/migrate.
5. Make the narrow correction needed for TEST4's existing evidence/operation recovery, and install the already reviewed owner/source-copy guidance at an idle point. Preserve current output and local history.
6. Use Review and continue only with its actual prerequisites satisfied. Send reuse instructions as a real conversation message, because an operator review note alone is not necessarily delivered to the model.
7. Let Clara finish the existing jobs in current queue order. Do not manually recreate packets or reprint already verified PDFs. Observe progress without fighting the worker for keyboard/mouse control.
8. Verify both actual handoffs and worker availability as described below. Update the context, commit/push your changes to the integration branch, and clearly identify what is installed and tested.

When a run pauses, identify the concrete wait/tool/event and duration. Prefer a small observation or bounded recovery. Do not generate increasingly long prompts, repeat the same failing detector, or make the user perform your diagnostic steps.

## 10. Code and document map

| Need | Read in Clara repository |
| --- | --- |
| Current decisions and detailed blockers | `CONTEXT.md` |
| Portal contract and integration setup | `docs/PORTAL-INTEGRATION.md`, `docs/PORTAL-V1-DEVELOPMENT.md`, `clara/contracts/portal-v1.json` |
| Assignment scope and handoff identity | `clara/portal_intake.py`, `clara/portal_bindings.py`, `clara/portal_results.py` |
| Worker cycles, receipts and recovery | `clara/portal_runtime.py`, `clara/portal_journal.py`, `clara/portal_recovery.py`, `clara/portal_quiescence.py` |
| File proof and stage completion | `clara/evidence.py`, `clara/workflows.py` |
| Existing remote operations and delivery | `clara/operations.py`, `clara/portal_delivery.py`, `clara/portal_outputs.py`, `clara/portal_hold_review.py` |
| Windows busy/held observations | `clara/portal_windows.py`, `clara/windows_activity.py`, `docs/WINDOWS-WORKER-HANDOFF.md` |
| Installation and startup | `Update-ClaraPortalTest.ps1`, `Set-ClaraAutostart.ps1`, `docs/AUTOMATIC-WINDOWS-STARTUP.md` |
| Skill content versus effective installation | `clara/config.py`, `clara/skill_pack.py`, `clara/starter_skills/taxprep-fast-path/SKILL.md` |
| Targeted regression coverage | `tests/test_sdk_message_buffer.py`, `tests/test_portal_windows.py`, `tests/test_portal_results.py`, `tests/test_portal_hold_review.py` |

In the portal repository, inspect `supabase/functions/_shared/claraServer.ts`, `claraHandoff.ts`, the `clara-result` and `clara-handoff-retry` entrypoints, and the existing workspace/review implementation. Have Lovable make any needed change.

Original Mac private records: `~/Downloads/Clearhouse-Lovable-Review/TaxPrep-Fast-Path-Test-Run.md`, `portal-return-current.txt`, `lovable-owner-build-completion.txt`, and the adjacent targeted RDP screenshots. They include exact runtime identifiers and output references intentionally omitted from this public document. Retrieve those from the actual portal/server if the Mac records are unavailable. Do not upload the raw records to GitHub.

## 11. Validation and definition of done

Previously passed tests are documented in `CONTEXT.md`: nine focused SDK/navigation checks, 52 Windows/runtime checks, and 15 owner-guidance checks; Lovable reported 92 portal checks. These are component results, not proof that both live tests completed. Use the environment's available Python; on the original Mac the project `.venv/bin/python` has dependencies while system `python3` does not.

For each TEST3/TEST4 closeout, completion requires observed evidence that:

- Required PDFs are correct for each assigned member/year and available in the intended OneDrive folder.
- PandaDoc links point to the intended existing packets with correctly assigned and placed signing fields.
- The portal accepts a real Ready to Email handoff with the correct folder/packet links and draft.
- The **original assigning staff account** owns the Ready to Email item. Do not inspect or alter the user's previously reassigned completed item to test this.
- No client message, signature or filing was sent/performed.
- The worker's required actions are settled and the next eligible job can start without duplicate processing.

Also verify normal chat is not labeled Ready to Email and that the portal accurately reflects a usable worker versus a held one. Autostart exists; its actual recovery/availability behavior still needs demonstration.

Keep a short completion record: what succeeded, what remains blocked, exact source/deployment revisions, installed revision, and validation performed. Give measured durations where available; do not claim a speculative speed improvement or an unsupported deadline.

Defer UI polish, new skills-management screens, ProFile, multiple workers, billing features and unrelated architecture changes until the existing workflow is demonstrated.

**Begin by inspecting the existing state and continue from the first unfinished step.**
