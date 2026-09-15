---
name: taxprep-fast-path
description: Print a Personal Taxprep T1 closeout efficiently using exact LW, T183 and ECL selection, Ctrl+R/Ctrl+P and printing by form across family members.
---

# TaxPrep T1 closeout navigation

Use this navigation for Personal Taxprep T1 closeouts, alongside the assigned closeout and firm delivery rules. Derived from the supplied TaxPrep UI map and improved fast-path guide; Laureen's transcript supplies the business sequence. Use Clara's current desktop tools directly, not the older agent's PowerShell function names. The supplied map records historical observations, including superseded notes; it is not a requirement to recreate that runner.

## Read once, then execute

Resolve the source, tax year, exact full member names, required documents and output folder once. Use `copy_file` to retain an untouched source snapshot in this run's folder, then make a separate live working copy for TaxPrep. Save the untouched snapshot's evidence ID in the source-copy checkpoint; never use the live editable return as the only source-copy proof. Open only the live copy, once. Preserve the original and the untouched snapshot with their hashes. Print settings or application metadata can change the live copy, so a final mismatch must be examined, not dismissed or used to replace an old proof's hash. Keep the member list and completed-file manifest in the checkpoint instead of discovering them again at each form.

Do not search for `Summary` or browse candidate summary forms. Obtain the current-year refund/balance from the printed client letter/return and compare it with the assigned closeout. Distinguish current-year balance from older arrears; missing figures are unknown, not zero. T183 is the signature authorization form, not a replacement for this comparison.

## Open the exact form

1. Focus the owned TaxPrep window. F4 opens Form Manager **inside the existing window**; do not wait for a new window named Form Manager.
2. Allow about 800 ms for the view, then Ctrl+F, Ctrl+A, and enter the jump code literally. Confirm the search box has focus before typing.
3. Allow at least 700 ms for filtering. Inspect the filtered rows once. **Select the exact Jump Code and matching description, not the first substring match.** `LW` may return multiple rows; choose exactly `LW`, Client Letter Worksheet. Use `T183` for T183 and `ECL` for the engagement letter.
4. Refocus TaxPrep after any observation that changes focus, activate that exact row and allow about 1.2 s for the form.

`LW` is the worksheet that configures the covering letter; `ECL` is the engagement letter. Both can produce a print dialog named **Print Form: Client letter**. That shared title and a similar default filename do not distinguish them. For ECL, verify engagement text such as “Personal Tax Return Engagement”, the agreement wording and signature/date block, using the generated letter (`edtAssembly`, a Rich Edit document) or its visible content. Do not require the print title to say ECL. For T183, verify the form title/content identifies T183.

If the exact row or expected content is absent, take one targeted observation and correct the navigation. Do not print a guessed form or repeatedly try unrelated results.

## Print order

1. **LW for all members:** open LW once, check each member, switching on the same worksheet. Check the applicable letter option, firm name/address and taxpayer name/address against the task's required letter. The applicable-letter group is a radio selection, not three independent checkboxes. Leave correct settings alone. Any necessary print-setting change is confined to the working copy; never overwrite the original return. Historical permission notes in the map do not grant permission to save the original.
2. **All client copies together:** Ctrl+R opens Print Tax Returns. Select exactly the assigned members in one pass. Clients ON, Clients PDF ON, Govt OFF; confirm other formats are not selected and Change status after printing is OFF. Verify actual named rows and checkbox states. Click OK once, then handle each member's Save As prompt. **The print dialog can stay open behind Save As until the final member is saved.** Wait for Save As, not for Print Tax Returns to disappear.
3. **All T183s:** open exact T183 once. Ctrl+P prints the current form/member to PDF. Save and verify it, switch member on the still-open T183, then Ctrl+P again. Do not return to Form Manager for each member.
4. **All engagement letters:** open exact ECL once and verify engagement content. Ctrl+P, save, switch member on the same letter, Ctrl+P. Do not print LW as the engagement letter.

For taxpayer/spouse, Alt+F7 toggles between those two members and preserves the form; allow about 1.5 s for the change. It does **not** reach dependants. For larger households use the named client selector and match the person's full consecutive name; the file/group row is not a person. Confirm the member in the Save As default name and resulting PDF even when the switch appeared successful.

## Printing and saving without detours

- Use Ctrl+R for the whole client return and Ctrl+P for the current T183/ECL. Do not walk the File/Print menus.
- Print dialogs are descendants of `TTPT1TaxApplication`, not necessarily desktop top-level windows. Stable IDs include `TTPT1PrintTaxReturn`, `TTPT1FormPrintForms`, `TCCHDiagForPrinting`, `PrinterListView` and `FileNameControlHost`. Numeric automation IDs in old captures are recycled handles. Use live labels/bounds or a current screenshot; do not reuse historical coordinates or scale the old calibrated offsets to another DPI.
- Print Form must have Print to PDF file selected. On the mapped build the printer list becomes disabled when this is selected; use this corroboration with the visible PDF setting. Do not send output to a physical printer.
- On Save As, read the default filename **including its Name property** (Text/Value may be empty), and match the expected member. Alt+N focuses File name; Ctrl+A then paste/type the literal full destination path with a tool that handles punctuation safely. Require readback of the complete path before Save. Include `.pdf` exactly once; only the older helper appended it automatically.
- Save As disappearing is insufficient: require the expected nonempty PDF at the exact path, correct member/year and document content. Inspect a reopened Save As before retrying; do not overwrite or reprint already verified files.
- Dismiss an automatically opened Send/View PDF Files window with Escape. Do not attach to the client file, publish to iFirm, transmit, sign or send emails.

Use bounded, condition-driven waits: Print dialog up to 60 s; return Save As up to 300 s; form Save As up to 180 s; Save As closing up to 120 s. These are ceilings, not sleeps. If the next expected dialog is present, proceed immediately. Watch for either Diagnostics or Print; do not pay a separate optional diagnostic timeout after Print is already visible (historical optional bounds: 15 s for a return, 5 s for a form).

Check for Save As with a short live-window/control observation first. The visible title `Save PDF File As` may not be exposed to a `text_exists` detector. If that detector misses once, inspect the owned window and its `File name` control or take a screenshot; do not spend 120 seconds repeating the same failed detector. Long ceilings apply only while printing is actually still in progress. Likewise, dismiss Send/View only if that optional window is present.

For Diagnostics, follow the task's approved printing rule. Retain the dialog evidence; a documented allowance to proceed with printing does not authorize filing or ignoring a wrong client/year or an amount discrepancy. If the warning needs an unprovided business decision, ask one short question with the specific issue, not a transcript of internal checks.

## Package and handoff

Use the assigned naming convention, normally `{Year} T1 {FirstName}.pdf`, `{Year} T1 {FirstName} T183.pdf`, and `{Year} T1 {FirstName} engagement letter.pdf`. Resolve any same-first-name collision explicitly. Remove excluded Note Summary **pages and bookmarks**, keeping the raw printed PDFs separately; inspect final letter and signature pages. Required additional forms come from this closeout, not another family's transcript.

Verify the complete package together after printing, retaining member/type/path/hash evidence. Use the existing signature and OneDrive delivery skills and portal checkpoints; PDF verification is not permission to skip the remaining workflow. For a portal closeout, reserve each PandaDoc packet and the OneDrive folder with `reserve_external_write` using the assignment's canonical keys shown in the task (`closeout:<form>:pandadoc:<member_id>`, `closeout:<form>:storage:folder`), never a title or timestamp; `record_portal_delivery` reconciles those reservations. PDFs go to OneDrive; the portal receives its folder link and each member's PandaDoc link for Ready to Email. Return the closeout to the exact staff account that assigned it to Clara: Amit's assignment returns to Amit, and a super admin's assignment returns to that super admin. Use the recorded assignment identity, never the OneDrive login or a fixed reviewer name. Laureen handles invoicing; she is not the default Ready to Email owner. The receiving staff member reviews the draft and handles sending. Clara does not send the email.

For T183 signing fields, locate **Part F — Declaration and authorization** and its actual signature/date lines in each final PDF. Do not infer their page from the total page count: the observed 2025 two-page print has Part F on page 1 and instructions on page 2. Current visible form content takes precedence over a historical skill's fixed page number. A clearly identified signature line on a different page is a layout difference, not a new approval requirement; never sign the document yourself.

In PandaDoc, inspect the editor's current frame; its outer page can contain only navigation text. The observed editor route is `/documents/`, not `/document/`. Do not wait in a two-minute `evaluate_script` polling loop for guessed URL/text conditions. Use one short observation, dismiss a visible optional detected-fields popup, and inspect the loaded document. Scroll Part F into view, then use a supported browser drag or native pointer action for the correct recipient's signature/date fields. Do not dispatch synthetic JavaScript drag events or reuse old page/viewport offsets. Verify the field visibly sits on the intended line after each drag; correct an existing misplaced field rather than layering duplicates. If a pointer action fails, take one fresh screenshot and adjust from the current layout.

At completion, close only task-owned temporary dialogs/apps once their outputs are verified. Preserve pre-existing apps and the source return. Record the first unfinished step on interruption; resume that step without recreating completed PDFs, folders or signature packets. Report stage durations, retries and model usage from actual logs so consecutive runs can be compared.
