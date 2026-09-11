# Clara · local agent prototype

Clara is a local chat application backed by the Claude Agent SDK. The model chooses tools and loads skills to work toward a requested outcome. It is independent of the existing fixed T1 pipeline.

**Build status, 11 September 2026:** the portable core and desktop dependencies installed on the Windows RDP server. After native Claude login, the first live task created, read and published a text file; a follow-up also completed, as shown in the user's dashboard screenshot. Release 0.1.3 adds download cards directly beneath the producing task, including in existing conversations. Thirty Python tests and a real Chrome/API attachment regression test pass on the development Mac. Live Windows desktop actions, browser actions, TaxPrep, Profile, PandaDoc and Drive still need testing. Existing portal integration is deferred as requested.

## Try it on this Mac

1. Open `Login-Clara.command` and finish the official Claude sign-in.
2. Open `Start-Clara.command`. It starts the local server and opens the authenticated dashboard.
3. In **Connections & settings**, add a folder containing synthetic test documents.
4. Ask Clara to find a document, inspect its contents and attach it. Use **Ask before commands & clicks** initially. Choose **Autonomous for this task** when you want commands and computer actions within your requested task to proceed without individual prompts.
5. Use **Skills library** to edit a skill or import `SKILL.md` / a ZIP with one skill and its resources.

If Clara is already running, use `Open-Clara.command`. Stop the server with Ctrl+C in its terminal. Stop an individual task using the dashboard's Stop button.

From a terminal in this folder:

```bash
.venv/bin/python -m clara login
.venv/bin/python -m clara serve
```

The dashboard runs at `http://127.0.0.1:8876`. The start/open command supplies a local access link to establish a browser session. Merely opening the address in a new browser does not grant command access.

## Install on Windows/RDP

### Install from GitHub with an existing embeddable Python

Repository: [nikitanikist/claraAgnet](https://github.com/nikitanikist/claraAgnet).

Download [Install-FromGitHub.ps1](https://raw.githubusercontent.com/nikitanikist/claraAgnet/main/Install-FromGitHub.ps1), then run it with the path to an existing, working Windows embeddable Python 3.12+:

```powershell
.\Install-FromGitHub.ps1 -PythonPath 'O:\path\to\existing\python.exe'
```

This clones into `%LOCALAPPDATA%\ClaraAgent` and runs portable setup. Use `-InstallDir` for a different new application folder. A later run updates a clean checkout with `git pull --ff-only` and refreshes dependencies when their requirements change. Stop Clara before updating. Use the firm's normal script execution method; the installer does not change execution policies. Native Claude sign-in follows installation, and Node.js is still needed for the browser connector.

### Standard Python installation or ZIP package

**Already have an embeddable Python with no pip/venv?** Use the [existing-runtime installer](docs/PORTABLE-WINDOWS.md). It provisions separate application-local runtimes. Node.js remains necessary for the browser connector, but missing Node no longer blocks the portable core setup.

Extract the source package into a persistent folder such as `C:\Clara`. Do not copy the Mac `.venv` or `node_modules` to Windows.

Prerequisites: 64-bit Python 3.12 or newer, Node.js 22 LTS (22.12 or newer), Chrome, and Git for Windows/Git Bash for Claude Code compatibility. Run the commands in the Windows user session that Clara should operate. The installer checks Python and Node; it does not change machine policies, create accounts or configure unattended Windows logins.

```powershell
cd C:\Clara
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-Clara.ps1
.\Login-Clara.ps1
.\Start-Clara.ps1
```

If PowerShell blocks the second or third script, invoke it with the same per-process `-ExecutionPolicy Bypass -File` form. This does not change the computer's persistent execution policy. Use the firm's approved execution method where applicable.

The installer creates the main `.venv`, installs the official SDK, and installs Chrome's MCP connector. Windows-MCP gets its own `.windows-venv` to avoid dependency conflicts. This is a **source installer requiring internet**, not a prebuilt offline executable. It does not install or alter TaxPrep/Profile.

Sign in with the intended user's own account through `Login-Clara.ps1`. In Settings, add a synthetic test folder first; enable Chrome and Windows desktop tools only when ready to test them. Website sessions use a dedicated Clara Chrome profile. Log into websites in that profile when prompted; existing ordinary Chrome sessions are not copied.

Read [the Windows acceptance checklist](docs/WINDOWS-ACCEPTANCE.md) before a real workflow.

## What is implemented

- Local chat with streamed text, real tool activity, Stop, necessary clarification/approval prompts, uploads, downloadable output files beneath each task and in Results, saved conversations and resumable SDK sessions.
- An open-ended Claude Agent SDK loop; no mandatory fixed T1 stage sequence.
- General recursive file search, PDF/DOCX/text reading, workspace text/script creation, PowerShell/Bash execution, and artifact publishing.
- Python libraries for Word, PowerPoint, Excel and PDF manipulation.
- Skills library with editing, Markdown imports and ZIP imports with relative resources.
- Four starter skills: finding client documents, office documents, live computer navigation, and a T1 closeout starter requiring the firm's actual SOP.
- Chrome DevTools MCP integration with a dedicated profile and Windows-MCP configuration for live accessibility/screenshot/click/typing tools.
- A single local executor, persisted event history, process-level workspace locking, and explicit interrupted state after restart. Interrupted tasks are not automatically replayed.
- Native sign-in status, model error reporting, tool availability checks and Windows input-desktop checks.
- A localhost dashboard with session cookies, origin/Host checks, request headers, upload limits and isolated output snapshots.

## What is not yet verified or implemented

- Live skill selection and moved-file recovery by the model beyond the first successful create/read/publish task.
- Native screenshots, popup recovery, disconnected/locked RDP behavior, TaxPrep or Profile automation.
- Real PandaDoc/Drive actions or a complete real-client T1 closeout.
- Current Clearhouse portal integration, multiuser authentication, a shared server billing design, remote workers, or multiple GUI tasks on one desktop.
- A custom Chrome extension. The existing general Chrome connector supplies browser tools without needing to build an extension first.
- Automatic model training, reliable self-modification or learning a firm's policy from an unreviewed transcript. Skills and conversation state provide reusable context.
- A Windows service or a guarantee of functioning after disconnect. The worker must have a usable interactive desktop; use the acceptance test to establish actual server behavior.
- General OCR, full Office rendering or spreadsheet formula recalculation. The installed document libraries support structural verification, not every visual check.

## Model access and cost

This prototype uses the official, unmodified Claude binary with the signed-in person's native subscription. It does not collect OAuth credentials, offer a custom Claude login, configure an API key, purchase credits, or fall back to an API/provider when the subscription fails. Clara removes billing/provider environment overrides from its own process and confirms a subscription auth method before a task.

A stored sign-in is not proof that its session can still authenticate: an earlier Mac test failed authentication. Fresh native login on Windows was followed by a successful live task. The dashboard records model authentication failures and directs the user back to native login when needed.

An SDK is not a separate cheaper model. It is the execution library. Account limits apply to subscription use; any extra-usage settings belong to the account. SDK-reported dollar estimates are not invoices or a measure of remaining Max allowance. Clara shows token counts and elapsed time. No billing fallback is configured, but the app cannot promise unlimited usage or independently override the user's provider-side extra-usage settings.

The current official help article pauses the announced SDK credit changes and says qualifying usage continues to draw from subscription limits. Separately, Anthropic's SDK/product guidance restricts developers routing end-user requests through their own Max credentials. This **individual local prototype is not a proven billing plan for a shared Clearhouse portal**. Resolve that deployment distinction before integrating multiple employees.

Sources checked 11 September 2026: [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [subscription usage update](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [authentication and product conditions](https://code.claude.com/docs/en/legal-and-compliance).

## Files and access

Data lives in `~/.clara` on Mac and `%LOCALAPPDATA%\Clara` on Windows. The application folder contains source and dependencies; the data folder contains settings, SQLite history, skills, uploaded files, output snapshots and the separate Chrome profile. Native Claude credentials remain under the official client's control.

Clara's file tools read only the workspace, uploaded references and configured read roots. They write only to the workspace. **Commands and computer tools run with the OS user's permissions; they are not sandboxed by that folder list.** Ask mode requests confirmation for commands and most browser/desktop actions. Autonomous mode allows those actions for the current task. The system instructions require task scope and verification; they are not a hard guarantee against every harmful action an OS-level tool could perform. Use an appropriate Windows user/workspace for the intended deployment.

The starter T1 skill does not authorize filings, client communications, signature invitations or signing on behalf of anyone. Those need the specific user's task authorization and the firm's process. The application itself executes no production closeout during setup or tests.

Outputs are copied to an attachment store before publishing, so later source edits cannot silently change an already-returned artifact. The UI does not expose arbitrary filesystem download paths. Stop halts the active execution and child commands; it does not undo completed actions.

## Development and tests

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check clara/static/app.js
node --test tests/test_chat_artifacts.mjs
```

The attachment test uses installed Chrome and Puppeteer bundled with the pinned browser connector (`npm ci`). It starts an isolated local API with synthetic history and no model calls. Set `CLARA_TEST_CHROME` or `CLARA_TEST_PYTHON` if their default executable paths differ. Screenshots are saved under ignored `runtime/ui-artifacts`.

For a fresh Mac installation, set `CLARA_PYTHON` to a Python 3.12+ executable if needed and run `bash scripts/install-mac.sh`.

`requirements.lock` records the resolved Python runtime versions on the development Mac. Windows selects native wheels and conditional dependencies; native Windows-MCP is separately pinned at its top-level version. The portable installation passed core and desktop import/CLI checks on the target server; desktop interaction remains untested. `package-lock.json` pins the browser connector. The Windows installer runs dependency checks.

After native login, either use the dashboard or stop the server and run:

```bash
.venv/bin/python scripts/live-smoke.py
```

This creates a synthetic client document in a moved folder and asks the real model to discover and attach it. It is a live subscription call, not an offline test. A passing result requires both successful execution and a real returned file. View its saved conversation after restarting Clara.

With connectors enabled in Settings, `python scripts/probe-connectors.py` checks their MCP tool discovery without model inference or performing browser/desktop actions.

See [validation results](docs/VALIDATION.md), [architecture](docs/ARCHITECTURE.md), and [portal integration notes](docs/PORTAL-INTEGRATION.md).
