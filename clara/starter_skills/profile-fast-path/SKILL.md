---
name: profile-fast-path
description: "Print a ProFile (.25T) T1 closeout efficiently: window-title proof of member and form, conditional preparer update, Print/Email PDF for the return, F12 for T183 and engagement letter, conditional extra forms, and the same package and handoff rules as TaxPrep."
---

# ProFile T1 closeout navigation

Use this for ProFile (.25T) T1 closeouts, alongside the assigned closeout and firm delivery rules. Derived from Laureen's walkthroughs and the recon measured on the live ProFile 2025.2.0 on 14-15 September 2026.

**ProFile is a different application from TaxPrep. Never reuse TaxPrep keystrokes.** In ProFile `Alt+F7` is Back track, not a member switch. `F12` = Print form. `F5` = spouse toggle (two-way only). `F4` = Form Explorer. `F3` = Client Explorer, whose index is EMPTY on this machine: never search by client name; the closeout gives the file path. The search box is the control named `Search` (class `TEdit`) at the top of the window; it is typeable.

## Spend turns sparingly

Every tool call is a round trip, and a run is mostly the sum of them. A measured ProFile closeout spent about two thirds of its wall-clock time between tool calls, with 55 screenshots against 29 clicks. The work was right; the pace was the cost.

ProFile's toolbar icons are not in the accessibility tree, so those keep the hover-read-tooltip-then-click rule below. Its dialogs are ordinary controls: the Print/Email PDF dialog, Save As, the file name field, the folder chooser and the audit panel can all be driven by `ActAndVerify`, which takes up to six actions plus the controls you expect afterwards, selects by name/automation_id/type rather than by pixel, refuses a missing, ambiguous or disabled control, and verifies the result. Use it for every sequence you can predict, above all replacing a pre-filled file name and pressing Save. It is faster than a screenshot-and-click pair and harder to get wrong.

Two limits decide what you may batch. A `toggle` step flips a checkbox rather than setting it, so read the current state first; this matters for the T1 EFILE job, which you must confirm is shown AND checked rather than flip blindly. And the expected controls prove a control is present, not what it holds: every value this skill requires you to read, the window title's member and form, "Clearhouse LLP" and "Q2629" on the T183, the file name before Save, you still read yourself. A passed batch is never proof of a value.

Take a screenshot when the next action truly depends on something unpredictable, when a step fails and you must inspect, or when you need visual proof. Do not take one to confirm what the call you just made already verified. Reading the window title is still the proof of member and form, and none of this removes a single verification this skill requires.

Before `save_checkpoint`, call `list_evidence` and pass the exact evidence IDs the stage requires; a verified stage is refused without them.

A wait is a ceiling, not a sleep. A dialog a keystroke opens appears in about a second: if your condition has not matched after roughly 8 s it is wrong, so look once and act on what is really on screen rather than sitting out the ceiling.

## Read once, then execute

Resolve the source path, tax year, exact full member names, required documents and output folder once from the closeout. Source names are inconsistently cased (`Singh, Inder pal and AURORA, AMRITA`): match case-insensitively. Files under `O:\Clearhouse Clara agent\Profile files\` are live client returns.

Use `copy_file` to retain an untouched source snapshot of the `.25T` in this run's folder, then make a separate live working copy and open only that copy, once. Save the snapshot's evidence ID in the source-copy checkpoint; preserve original and snapshot with their hashes. Printing from a copied `.25T` is unproven: if ProFile behaves differently on the copy (refuses, warns), stop and ask rather than opening the original.

## Open and identify

1. Launch ProFile with the working-copy path as the argument. Do not use `F3` or any name search.
2. Read the main window title (`TDlgProfileMain`): `ProFile - [{year} T1/TP1: {Member} - {Form}]`. It names the current member and form: treat it as the proof of every member switch and every form open. Which member ProFile opens on is not predictable: always read the title.
3. Open the Info form (tab at the top, or type `Info` in the Search box) and prove the client identity against the closeout before anything that writes, and again before the first print; a mismatch is a stop and ask.

Toolbar buttons are not in the UI tree. Coordinates here were measured at 1920x1080, 96 DPI and must be confirmed before every click: hover the button, read the `THintWindow` tooltip (its `Name` is the text), click only if it matches.

## Preparer information (conditional)

1. Read the audit panel (`TAuditListBox`), Notices tab, for the Notice "The preparer, discounter or trustee information on this return does not match the information in Options|Environment. To update the preparer information on this return, open the Info form, right click, and select 'Update preparer information'."
2. Notice ABSENT: do nothing. Do not update. Do not write to the file.
3. Notice PRESENT: Info form, right click, "Update preparer information". No save afterwards. Re-read Notices as proof it cleared.
4. A firm other than Clearhouse LLP shown in the preparer details is neither case Laureen described: stop and ask.

Never modify `Options -> Environment` or `Options -> Form Selection`: shared configuration, verification is read-only, setup is Laureen's. In the Form Selection dialog `Enter` = OK and commits: never press Enter there; leave with Cancel.

`EFILE: Not eligible`, `EFILE#1320` and the T183 missing signature date/time warnings are NORMAL at print time: never stop on them. The preparer-mismatch Notice IS actionable. Distinguish by message; never dismiss the panel as a class.

## Print the return

1. Record the ProFile output folder's contents BEFORE building.
2. `File -> Print/Email PDF`. Confirm "T1 EFILE" is shown AND checked. ProFile picks the job from the return's EFILE flag; if it shows `T1 Paper` or another job, stop and ask.
3. Build PDF. A folder opens where the PDF was generated.
4. Identify the exact new file this run produced against the pre-build listing. Never rely on "newest file" alone; a wrong pick is another client's return.
5. COPY (never cut) it to the package folder. Verify it arrived and opens. Only then remove your own source file from the output folder.
6. Never delete or move any other file in that output folder; other runs and other clients own them.
7. Rename to `{Year} T1 {FirstName}.pdf`.

This route may print one member or all (unverified): check the printed PDF for every assigned member; if one is missing, switch member (see Members) and repeat.

## Print T183

1. Open T183: its tab at the top if open, else type `T183` in the Search box.
2. Read the window title: it must name the intended member and the T183 as the form.
3. Confirm BOTH "Clearhouse LLP" AND "Q2629" appear on the form. Either missing: abort and escalate; do not print.
4. Press `F12`, or hover `789,71` and click only if the tooltip identifies the green print-to-PDF printer (the plain printer at `757,71` is NOT it).
5. Choose the package folder. REPLACE the pre-filled file name with `{Year} T1 {FirstName} T183.pdf`. Read back the full path before Save; verify the PDF exists and opens.

## Print engagement letter

1. Type `engage` in the Search box; the letter is not usually already open.
2. PROVE from the window title that the engagement letter is the form in focus (`... {Member} - Engagement letter`). `F12` and the green printer print whatever is focused; an unnavigated search would print the previous form under the wrong name. If you cannot prove it, abort.
3. `F12` or the confirmed green printer; package folder; replace the name with `{Year} T1 {FirstName} engagement letter.pdf`; verify.

## Conditional extra forms and naming

Open the printed T1 PDF. Read its bookmarks (the more reliable signal) and the client letter for a T1135, instalments or any other form that applies. Print each mentioned form the same way as the T183: search, prove form and member from the title, `F12`, package folder, replace name, verify. Test files: `Anderson, Patrick.25T` (single, reference package), Langlet/Chung (couple; Jeff has instalments), Singh/Aurora (couple; both T1135).

Naming (same as TaxPrep, one exception):

- Package folder `{Year} T1 Package`; client copy `{Year} T1 {FirstName}`; T183 `{Year} T1 {FirstName} T183`; engagement letter `{Year} T1 {FirstName} engagement letter`.
- Instalments `{ReturnYear+1} Instalments - {person}` (a 2025 return gives `2026 Instalments`): the ONLY output whose year is not the return year; do not "correct" it. Per person: print and name only for the member whose return requires instalments (Jeff yes, Janice no).

Never write a file without the client name in it.

## Verify

1. Open the printed T1 PDF. The client letter must be the FIRST page. If not, setup A2 has drifted: abort, print nothing further, escalate.
2. Scan the whole PDF for audit notes, memos or tapes content. Any present: setup A3 has drifted, abort and escalate.
3. Confirm the member's name and the tax year.
4. Amounts trap: the status bar `Balance/Refund` is Taxes Payable, NOT the client-email figure. Amount Owing / Refund = Taxes Payable + Prior Balance (Chung: -9,528.64 + 327.07 = -9,201.57; Singh: 3,370.24 + 24,971.76 = 28,342.00). Compare the closeout's figure against the right field; if a genuine difference remains, escalate with the arithmetic; never guess.

## Members

Two controls exist. `F5` and the icon at `474,71` (tooltip "Switch to the spouse's form (F5)") toggle taxpayer <-> spouse only; a third person is unreachable. The family-member selector is the second icon at `512,71` (arrow `529,71`, tooltip "Switch to another family member's return"): greyed out on a couple, enabled on 3+ members, listing names.

- Never build the member loop on `F5`; on a couple use it for the one switch and read the title back.
- For more than two members use the selector. If it is greyed, or its list does not name the expected member, stop and ask: the dropdown has never been exercised on a real family file.
- Hover and read the `THintWindow` before every click; the two icons are adjacent.
- After every switch read the window title, and confirm the member again in each resulting PDF. Print T183, engagement letter and extra forms for each assigned member; re-read the title before each `F12`.

## Hard stops

- Never send anything to a client; stop at Ready to Email. Never e-file or transmit.
- Never write to the client's return except the conditional preparer update.
- Never delete or move another client's file in the ProFile output folder.
- Never press Enter in Form Selection; use Cancel. Never modify `Options -> Environment` or `Options -> Form Selection`.
- Two sources disagree: stop and ask.
- Never answer a save prompt automatically. If ProFile asks to save on close, answer No only if the task authorizes it; otherwise ask.

## What is still unverified: stop and ask

The family-member dropdown (needs a `.25T` with a dependant); A3 (the Verify scan is the only check); `carry forward` in Form Selection; the `T1 Paper` job for EFILE=0 returns; whether Print/Email PDF prints one member or all; whether ProFile prompts to save on close after a preparer update, and what to answer; printing from a copied `.25T`; T3s ("usually" is a hedge). The closeout's `software` field is the routing: only a closeout marked ProFile reaches this skill.

## Package and handoff

Use the assigned naming convention, normally `{Year} T1 {FirstName}.pdf`, `{Year} T1 {FirstName} T183.pdf`, `{Year} T1 {FirstName} engagement letter.pdf`, plus `{ReturnYear+1} Instalments - {person}.pdf` and any T1135 or other conditional form the printed return requires, all in `{Year} T1 Package`. Resolve any same-first-name collision explicitly. Keep the raw printed PDFs separately and inspect the final letter and signature pages. Required additional forms come from this closeout's printed return, not another family's.

Verify the complete package together after printing, retaining member/type/path/hash evidence. Use the existing signature and OneDrive delivery skills and portal checkpoints; PDF verification does not permit skipping the remaining workflow. For a portal closeout, reserve each PandaDoc packet and the OneDrive folder with `reserve_external_write` using the assignment's canonical system, operation and key triples shown in the task (`pandadoc create_signature_packet closeout:<form>:pandadoc:<member_id>`, `storage create_folder closeout:<form>:storage:folder`), never another operation name, a title or a timestamp; `record_portal_delivery` reconciles those reservations. Its `files` records use the assignment's `member_id` values, `document_type` exactly `client_copy`, `t183` or `engagement_letter` (and `instalments` or `t1135` for the extra forms; verify those with `verify_output` types `instalments` and `t1135` first), and the assignment `tax_year`; each observation must be a Chrome readback from this task (at most 20 minutes old) showing the folder ID, file ID, exact file name and exact byte size (read item details or the storage API), and each packet observation must show the PandaDoc URL, document ID, member name and email. The canonical keys are bound by the reservations, not by page text. On a continued attempt, read the folder, its files and each packet again and call `record_portal_delivery` again before finishing: the portal accepts only readbacks from the attempt that hands off, and recording again creates nothing remotely. PDFs go to OneDrive (instalments and T1135 included); the portal receives its folder link and each member's PandaDoc link for Ready to Email. Return the closeout to the exact staff account that assigned it to Clara: Amit's assignment returns to Amit, and a super admin's assignment returns to that super admin. Use the recorded assignment identity, never the OneDrive login or a fixed reviewer name. Laureen handles invoicing; she is not the default Ready to Email owner. The receiving staff member reviews the draft and handles sending. Clara does not send the email.

For T183 signing fields, locate **Part F — Declaration and authorization** and its actual signature/date lines in each final PDF. Do not infer their page from the total page count; current visible form content takes precedence over a fixed page number. A signature line on a different page is a layout difference, not a new approval requirement; never sign the document yourself.

In PandaDoc, inspect the editor's current frame; its outer page can contain only navigation text. The observed editor route is `/documents/`, not `/document/`. Do not wait in a polling loop for guessed URL/text conditions; use one short observation, dismiss a visible optional detected-fields popup, and inspect the loaded document. Scroll Part F into view, then use a supported browser drag or native pointer action for the correct recipient's signature/date fields. Do not dispatch synthetic JavaScript drag events or reuse old page/viewport offsets. Verify the field visibly sits on the intended line after each drag; correct an existing misplaced field rather than layering duplicates. If a pointer action fails, take one fresh screenshot and adjust from the current layout.

At completion, close the dialogs and applications you opened for this task once their outputs are verified; this includes any ProFile or browser window you opened. Programs already open before the task belong to whoever opened them: leave them, unless one blocks your work (a ProFile window holding the file you need, a dialog covering the screen), in which case close it with its normal close control and never discard unsaved work that is not yours; if it asks to save someone else's changes, cancel and ask the staff member. Preserve the source return. Record the first unfinished step on interruption; resume that step without recreating completed PDFs, folders or signature packets. Report stage durations, retries and model usage from actual logs so consecutive runs can be compared.
