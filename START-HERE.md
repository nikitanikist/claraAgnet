# Clara 0.2.5 is ready for Windows qualification

This update adds Chrome setup, fresh Windows observations and focus checks, workflow checkpoints, verified document evidence, reviewed procedural memory, searchable references, 18 CPA skills, total workflow budgets and local diagnostics. It preserves edited skills and saved conversations. The existing Clearhouse portal and old T1 script are not modified.

Version 0.2.2 adds the missing production HTTP client and verifies isolated dashboard startup before setup reports success. If startup showed `No module named httpx`, pull this release and rerun the updater to refresh the runtime.

Version 0.2.1 also fixes the Windows temporary-database lock during backup. If 0.2.0 showed `WinError 32` while deleting a temporary `clara.sqlite3`, pull this fix before running the updater again. That error was caused by an open backup connection, not evidence that Clara was still running.

Version 0.2.5 improves questions, evidence lookup, diagnostics and timing reports. **Connections & settings → Reasoning effort** defaults to **Balanced** while keeping your model selection. See [the repeat-test guide](docs/DELIVERY-IMPROVEMENTS.md).

## Update the existing RDP installation

Stop Clara with Ctrl+C in its server PowerShell window. In a new PowerShell window:

```powershell
Set-Location "$env:LOCALAPPDATA\ClaraAgent"
.\Update-Clara.ps1
```

For the existing 0.2.4 installation, the updater makes a local data backup, checks for source edits, pulls the new code and verifies setup. If it reports an error, keep that output and do not start another update. The earlier 0.2.0 backup fix is documented in the release history.

When setup passes, run:

```powershell
.\Start-Clara.ps1
```

The browser installer uses compatible Node if available or downloads a checksum-verified Node into Clara's own folder. It does not require an administrator installation. Your server must allow those executables under its normal policies. Google Chrome and the existing approved Python/Git installation are required.

## Resume after reaching a turn limit

Version 0.2.3 accepts larger turn counts such as 500 and adds **No turn limit**. Existing limits are preserved until you explicitly change them.

1. In **Connections & settings**, check **No turn limit** and save. This removes the limit for future requests.
2. Select the paused conversation. If it has a workflow, open **Workflow review**, check **No turn limit** under **Workflow budget**, add a short reason and save. This removes its separate accumulated turn limit while retaining checkpoints and usage.
3. Return to the same conversation and ask Clara to inspect current windows and saved outputs, then continue from the first unfinished step. Do not restart the whole closeout.

Time and API-estimate limits remain configured separately for the request and workflow. Check remaining workflow time/cost before continuing; change them only if you intend to. Claude account limits and the Stop button still apply. No model-turn cap is passed to the SDK when both applicable turn limits are disabled.

## Resume after stopping a task

Version 0.2.4 adds recovery from a stopped request whose SDK usage report is incomplete. This can happen when Stop is pressed while Clara is waiting for a permission answer. Completed actions are not undone; keep the existing folders and application windows.

1. Update and restart Clara using the commands above. Refresh the dashboard and confirm **LOCAL · 0.2.5**.
2. Open the same paused conversation, then **Workflow review**. Under **Resume saved work**, inspect the stopped-task information and select **Allow continuation with incomplete usage**.
3. Clara returns to the same chat with a continuation message filled in. Press **Send**. The agent receives its saved workflow state and previous tool observation, with instructions to inspect current windows and outputs and continue from the first unfinished step.

This action records your acknowledgement of missing usage. It does not mark the closeout complete, change its budget, erase usage or replay any application action. Unknown amounts remain unknown; accumulated turn/cost totals are lower bounds. If the known time/cost/turn budget is exhausted, update it separately in Workflow review. A new interruption needs a new review.

**Autonomous for this task** is now the default. You can change the saved preference under **Connections & settings → Default task mode**, or choose Ask for an individual task. Existing jobs keep their original mode. The recovery button prepares a message but does not submit it.

## First tests

1. In **Connections & settings**, enable Chrome and Windows tools and add your test folders. Keep the RDP session usable while testing.
2. Ask Clara to open a harmless test website and inspect it. Websites use Clara's separate Chrome profile; sign into PandaDoc/OneDrive in that profile when required.
3. In **Knowledge & memory**, import the relevant TaxPrep/ProFile manual sections and firm SOP. Record application build and tax year. Shipped official links are a source index, not entire manuals.
4. Create a new conversation. In **Workflow review**, create a **T1 print test** with the actual test client key, year and member names.
5. In Workspace, provide the source file/folder and request the client-copy print test. Ask Clara to verify the PDF, save evidence and attach a handoff. Use autonomous mode only for the task scope you intend.
6. Inspect the workflow stages, PDF and usage. If the task stops, continue in that conversation after reviewing progress; its workflow budget does not reset. Budget changes are recorded in Workflow review.
7. Qualify the complete closeout with firm-approved signature, billing and delivery details after printing works. See [CPA acceptance](docs/CPA-ACCEPTANCE.md).

The local Python suite has 99 passing tests, plus real Chrome MCP and dashboard tests. The new native Windows bridge and complete TaxPrep closeout have not been independently tested on the target server. A live-model call on the Mac also needs native sign-in. This is a qualification candidate, not a declaration that the whole firm workflow is already production-qualified.

[Implementation and limits](docs/PRODUCTION-IMPLEMENTATION.md) · [Backup and rollback](docs/UPDATE-AND-ROLLBACK.md) · [Portal protocol](docs/PORTAL-PROTOCOL.md) · [Usage interpretation](docs/USAGE.md)
