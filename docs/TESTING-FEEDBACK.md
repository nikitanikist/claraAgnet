# Clara testing feedback

Last updated: 11 September 2026

## Working agreement

The user explicitly requested the combined update on 11 September 2026: implement the two recorded behavior changes together with per-task token and cost reporting. These changes are included in release 0.1.4.

## F001 — Close temporary windows after completing a task

Status: Implemented in 0.1.4; live Windows acceptance remains to be run.

User report: Clara successfully found a client's file path, but left the File Explorer window used for the search open after reporting the result.

Expected behavior: When a task is complete, Clara should close File Explorer windows she opened only to carry out that task, leaving the desktop tidy.

Implementation considerations for the later update:

- Track which windows Clara opens during the task, so cleanup targets those windows.
- Preserve windows that were already open, windows the user explicitly wants left open, and visible results still needed for review.
- Do not discard unsaved work during cleanup.
- If the task is waiting for clarification or review, distinguish that from completion before cleaning up.
- Verify cleanup and then report completion.

Acceptance check: Start with a user-owned Explorer window open. Ask Clara to find a file using a separate task window. After returning the verified path, the temporary window closes and the original window remains open. An explicit request to leave a result visible is respected.

## F002 — Choose the fastest reliable method for each task

Status: Implemented in 0.1.4; live Windows acceptance remains to be run.

User report: To find a client's file path, Clara opened File Explorer and navigated drives and folders with desktop tools. The user expects Clara to choose a direct file search or targeted PowerShell command when that can complete the same task faster and accurately.

Expected behavior: Select tools according to the requested outcome, available capabilities and verification needs. Minimize unnecessary navigation and tool calls without sacrificing accuracy. A general command or file-search tool should not require building a dedicated workflow script first.

Implementation considerations for the later update:

- For a file-path request, prefer the existing file-search tool in an authorized, relevant folder. Use a targeted read-only PowerShell command when it is appropriate and permitted.
- Start with known client folders, filename patterns, extensions and other supplied clues; widen the search deliberately when needed. Avoid searching every drive by default.
- Verify the candidate exists and matches the requested client, document type and year when supplied. Inspect content when a filename is insufficient; resolve ambiguous matches before selecting one.
- Treat partial searches, timeouts and inaccessible folders as limits on the result, not proof that a file does not exist.
- Use desktop tools for tasks that actually require an application's interface, such as operating Softros LAN Messenger, or when direct access cannot provide the required result. Respect an explicit request to demonstrate GUI navigation.
- Inspect current capability/settings evidence when selecting a method. The existing code already exposes search_files and run_command and instructs direct filesystem operations for file tasks; investigate why they were not selected in the reported run rather than assuming the tools are absent.
- Compare elapsed time, unnecessary tool calls and verified results on representative tasks. The fewest clicks alone is not the success criterion; a broad command search can also be slow.

Acceptance check: Given a file-path lookup in a configured test folder, Clara searches directly, verifies and returns the correct path without opening Explorer. Repeat with a moved file and ambiguous filenames. A native application task still selects desktop tools when needed.

## F003 — Measure tokens and estimated cost per task

Status: Implemented in 0.1.4; backend and browser regression tests pass.

User request: After a task finishes, report the complete run's tokens and estimated cost, so the user can compare closeout runs, understand subscription consumption and share results with the client.

Implementation: A task usage card shows token totals, input/output/cache breakdown, SDK USD estimate, model breakdown, elapsed time and turns. Conversation totals cover its finished tasks and a CSV export provides a row for each task. Existing saved usage is displayed without rerunning tasks. A blended estimate per 1,000 tokens is a run-specific average, not a flat provider rate.

An optional task estimate limit is passed to the SDK. It does not measure or cap the account's remaining Max allowance. Missing or interrupted usage is explicitly incomplete; it is never substituted with zero cost. A full closeout still needs to run before its usage can be measured.

## Implementation notes for F001 and F002

- The system instructions now specify targeted direct search and verification before GUI file navigation. They apply to existing installations after restart without overwriting user-edited skills.
- A native read-only observer compares Explorer windows around Windows tool actions. A one-time Stop hook asks the model to inspect remaining candidates and close only temporary windows it confirms it opened. It does not blindly close handles or kill processes. The model must preserve existing windows, unsaved work and requested visible results.
- Unit tests cover candidate selection, already-closed windows, no extra cleanup round for direct file tasks, inaccessible desktops and preventing repeated cleanup loops. This is not proof of live Windows behavior; test both search selection and cleanup on RDP after updating.

## Earlier observations

- Downloads were visible only in Results despite Clara describing an attachment in chat. Addressed in release 0.1.3 with download cards beneath the producing task.
- Enabling the unavailable Chrome connector prevented a Windows desktop task from starting. The current configuration workaround is Chrome tools off and Windows desktop tools on. The user subsequently reported that the Softros LAN Messenger test worked. Connector startup behavior has not been changed.

Application changes were deferred during feedback collection and are now included at the user's explicit request.
