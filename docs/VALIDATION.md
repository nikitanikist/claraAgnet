# Validation record · 11 September 2026

## Verified on the development Mac

- 23 automated tests pass. They cover moved-file discovery, PDF content extraction, external-root reads, blocked path traversal/symlink escapes, protected skill paths, immutable artifact snapshots, ZIP skill resource handling and rejection of unsafe archives, real command execution/timeouts, Word/PowerPoint/Excel creation and reopening, interruption recovery, billing environment filtering, local HTTP authentication/origin checks, file upload/download, job/event persistence, settings/skill APIs, queue serialization/cancellation/questions, exclusive process locking, and SDK message/session/error handling with a test double.
- Python dependency check reports no broken requirements.
- Python source compilation and JavaScript syntax checks pass. Mac shell launchers pass `bash -n`.
- The real Claude Agent SDK 0.2.152 imports and starts the official CLI protocol. Its matching bundled Claude binary is 2.1.259. A connection-only probe succeeds without submitting a model prompt. MCP initialization may be deferred until a task; this probe alone does not prove tool readiness.
- An earlier task using the installed Claude CLI 2.1.220 connected the real Clara MCP server and advertised the seven custom tools plus SDK tools. That model request failed authentication and returned zero input/output tokens; it did not produce an artifact.
- The current matching bundled CLI reports no native sign-in. `Login-Clara.command` / `Login-Clara.ps1` uses that official binary's login flow. No credentials were extracted or copied between clients.
- Chrome DevTools MCP 1.9.0 started over stdio and advertised 24 browser tools. No browser navigation, clicks, screenshots or website transactions were executed during this check.
- Local dashboard, JavaScript, CSS and health routes returned HTTP 200. The protected API returned 401 without a local session and worked after a valid bootstrap exchange. Four starter skills are discoverable in the API.

The test suite emits one upstream Starlette/AnyIO deprecation warning about its test client. No test failures remain in the recorded run.

## Release 0.1.1: existing Windows runtime setup

- The user's RDP output confirms Python 3.12.8, 64-bit, with pip/venv/ensurepip absent. The ordinary MSI installer was rejected with error 1625 and the RDP account has no administrator rights.
- The revised installer uses a separate copy of that existing embeddable interpreter, with application-local dependencies. It does not download another Python runtime or change Windows policy.
- The full local suite now passes **29 tests**. Six added tests cover preserving the original runtime, excluding old application files/paths, rejecting overlapping or unrelated destinations, retry/version handling, bootstrap wheel checksum/archive validation, clearing readiness after failed verification, and portable connector selection.
- The pinned pip 26.2.1 wheel was downloaded, its SHA-256 verified, and its setup runner successfully executed under isolated Python on the Mac.
- Cross-platform dependency dry runs selected Windows x64 / CPython 3.12 wheels for both requirements files. This checks wheel availability and resolution from the Mac; Windows-specific environment markers and imports still require the real target run.
- Windows execution of the revised installer and launchers is pending. Browser setup reports pending when Node.js is absent. No live model or desktop actions were performed for this release.

## Requires the user / target environment

Release 0.1.2 adds the GitHub clone/update entry point for `nikitanikist/claraAgnet`. The suite now passes **30 tests**, including dependency refresh when a Git update changes a requirements file. Windows execution of the new PowerShell entry point remains pending; no execution policies are changed by it.

| Area | Status | What establishes success |
|---|---|---|
| Live Claude reasoning and tool selection | Blocked by native sign-in | Fresh login, then a real task finds/verifies/attaches the synthetic document |
| Skill selection by the live model | Pending | Model invokes the relevant skill during a successful task |
| Live session continuation | Pending | Follow-up refers correctly to the previous result in the real SDK session |
| Browser behavior | Discovery passed; actions pending | A harmless page task succeeds with live DOM evidence |
| Native Windows installer | Not executed on Mac | Installer, dependency checks and doctor succeed on Windows |
| Windows desktop / RDP | Not tested | Notepad, popup, stop, lock and disconnect acceptance checks |
| TaxPrep / Profile | Not tested | Correct package from a test return under the firm's SOP |
| PandaDoc / Google Drive | Not tested | Authorized test account operations with actual destination evidence |
| Existing portal | Not integrated | Portal authentication, jobs, results and supported billing connected later |
| Visual frontend / accessibility QA | Not performed | User walkthrough or explicitly requested browser testing |

Do not interpret offline adapter tests, tool discovery or an HTTP 200 as evidence that an autonomous tax closeout works. They establish the local application's groundwork; model and Windows acceptance are the next milestones.

## Reproduce

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q clara scripts
node --check clara/static/app.js
bash -n Start-Clara.command Login-Clara.command Open-Clara.command scripts/install-mac.sh
.venv/bin/python scripts/probe-sdk.py
```

After sign-in, use `scripts/live-smoke.py` with the server stopped, or run the equivalent task in the dashboard. Connector discovery uses `scripts/probe-connectors.py` with the desired connectors enabled in Settings. The Windows checklist documents the remaining target-platform checks.
