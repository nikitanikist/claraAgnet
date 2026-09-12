# Clara 0.2.1 is ready for Windows qualification

This update adds Chrome setup, fresh Windows observations and focus checks, workflow checkpoints, verified document evidence, reviewed procedural memory, searchable references, 18 CPA skills, total workflow budgets and local diagnostics. It preserves edited skills and saved conversations. The existing Clearhouse portal and old T1 script are not modified.

Version 0.2.1 also fixes the Windows temporary-database lock during backup. If 0.2.0 showed `WinError 32` while deleting a temporary `clara.sqlite3`, pull this fix before running the updater again. That error was caused by an open backup connection, not evidence that Clara was still running.

## Update the existing RDP installation

Stop Clara with Ctrl+C in its server PowerShell window. In a new PowerShell window:

```powershell
Set-Location "$env:LOCALAPPDATA\ClaraAgent"
git status --short
git rev-parse HEAD
git pull --ff-only origin main
if ($LASTEXITCODE -eq 0) { .\Update-Clara.ps1 }
```

Keep the old revision printed by `git rev-parse HEAD`. If local edits are listed, preserve them before updating. This first pull obtains the new updater; it then creates a local data backup before refreshing dependencies. Future updates can run `Update-Clara.ps1` directly. Do not simply restart after pulling: this version includes a browser runtime setup and Windows bridge probe.

When setup passes, run:

```powershell
.\Start-Clara.ps1
```

The browser installer uses compatible Node if available or downloads a checksum-verified Node into Clara's own folder. It does not require an administrator installation. Your server must allow those executables under its normal policies. Google Chrome and the existing approved Python/Git installation are required.

## First tests

1. In **Connections & settings**, enable Chrome and Windows tools and add your test folders. Keep the RDP session usable while testing.
2. Ask Clara to open a harmless test website and inspect it. Websites use Clara's separate Chrome profile; sign into PandaDoc/OneDrive in that profile when required.
3. In **Knowledge & memory**, import the relevant TaxPrep/ProFile manual sections and firm SOP. Record application build and tax year. Shipped official links are a source index, not entire manuals.
4. Create a new conversation. In **Workflow review**, create a **T1 print test** with the actual test client key, year and member names.
5. In Workspace, provide the source file/folder and request the client-copy print test. Ask Clara to verify the PDF, save evidence and attach a handoff. Use autonomous mode only for the task scope you intend.
6. Inspect the workflow stages, PDF and usage. If the task stops, continue in that conversation after reviewing progress; its workflow budget does not reset. Budget changes are recorded in Workflow review.
7. Qualify the complete closeout with firm-approved signature, billing and delivery details after printing works. See [CPA acceptance](docs/CPA-ACCEPTANCE.md).

The local Python suite has 74 passing tests, plus real Chrome MCP and dashboard tests. The new native Windows bridge and complete TaxPrep closeout have not been independently tested on the target server. A live-model call on the Mac also needs native sign-in. This is a qualification candidate, not a declaration that the whole firm workflow is already production-qualified.

[Implementation and limits](docs/PRODUCTION-IMPLEMENTATION.md) · [Backup and rollback](docs/UPDATE-AND-ROLLBACK.md) · [Portal protocol](docs/PORTAL-PROTOCOL.md) · [Usage interpretation](docs/USAGE.md)
