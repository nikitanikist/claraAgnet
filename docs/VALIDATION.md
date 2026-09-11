# Validation record · 11 September 2026

## Initial development Mac checks (before Windows installation)

- 23 automated tests pass. They cover moved-file discovery, PDF content extraction, external-root reads, blocked path traversal/symlink escapes, protected skill paths, immutable artifact snapshots, ZIP skill resource handling and rejection of unsafe archives, real command execution/timeouts, Word/PowerPoint/Excel creation and reopening, interruption recovery, billing environment filtering, local HTTP authentication/origin checks, file upload/download, job/event persistence, settings/skill APIs, queue serialization/cancellation/questions, exclusive process locking, and SDK message/session/error handling with a test double.
- Python dependency check reports no broken requirements.
- Python source compilation and JavaScript syntax checks pass. Mac shell launchers pass `bash -n`.
- The real Claude Agent SDK 0.2.152 imports and starts the official CLI protocol. Its matching bundled Claude binary is 2.1.259. A connection-only probe succeeds without submitting a model prompt. MCP initialization may be deferred until a task; this probe alone does not prove tool readiness.
- An earlier task using the installed Claude CLI 2.1.220 connected the real Clara MCP server and advertised the seven custom tools plus SDK tools. That model request failed authentication and returned zero input/output tokens; it did not produce an artifact.
- At that stage, the matching bundled CLI on the Mac reported no native sign-in. `Login-Clara.command` / `Login-Clara.ps1` uses that official binary's login flow. No credentials were extracted or copied between clients.
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

## Windows milestone and release 0.1.3

Release 0.1.2 added the GitHub clone/update entry point for `nikitanikist/claraAgnet`. The user's target-server screenshots now confirm portable core and desktop installation, native imports/CLI help, and native Claude login followed by a successful model task. Clara created, read and published `clara-first-test.txt`; the dashboard showed a 19-byte download in Results. A follow-up about the same file also completed. This evidence comes from the user's screenshots; it is not a direct independent inspection of the remote file.

The screenshot also exposed a UI issue: downloads appeared only in the side panel while Clara described an attachment in chat. Release 0.1.3 adds cards beneath the producing task, with filenames and download links, while retaining Results. Existing conversations acquire the cards when their saved history loads; no model rerun is required.

The **30 Python tests** pass. One added real Chrome/API regression test verifies actual downloaded file contents, history reload, multiple files, association with the producing task, duplicate event handling, streaming response replacement, escaped filenames, mobile card bounds and conversation reset. It uses temporary synthetic data and makes no model requests. Desktop and mobile screenshots were visually inspected on the Mac. This does not establish live browser-agent or native Windows GUI readiness.

## Release 0.1.4: usage reports and collected feedback

- **43 Python tests pass.** New coverage includes all-model usage totals, independent follow-up costs, deduplicated partial input counts, missing/zero/crash results, budget-crossing usage, unknown model prices, fallback to reported model estimates, authenticated CSV export, CSV formula escaping, budget validation and runtime interruption persistence.
- The real Chrome/API regression passes for usage cards beside their tasks, old saved records, conversation totals without duplication, actual CSV download, estimate-limit settings and mobile bounds, alongside the previous artifact tests. Desktop/mobile screenshots were inspected. Data and dollar values in this fixture are synthetic, not measured closeout costs.
- No dependencies changed. Python compilation, JavaScript syntax and diff checks pass. The existing SDK supports the Stop hook and `max_budget_usd`; the latter is passed into each task's options and covered by the adapter test.
- The user reported that the Softros LAN Messenger task worked after turning Chrome tools off and Windows desktop tools on. The reported file search also worked through Explorer, exposing the two feedback items.
- File-tool preference is strengthened in the system instructions without overwriting imported/user-edited skills. The Explorer observer and one-time Stop review have unit coverage for candidate selection, preservation of preexisting windows, already-closed windows, inaccessible snapshots and avoiding loops. Native enumeration and the model's actual cleanup/strategy choices must be checked on the target Windows server. No Windows action was performed from the Mac for this update.
- Actual cost and token consumption for a complete T1 closeout remain unmeasured. Reporting and an estimate limit do not reveal or guarantee the remaining Max allowance. See [usage interpretation](USAGE.md).

## Remaining target-environment validation

| Area | Status | What establishes success |
|---|---|---|
| Live Claude reasoning and tool selection | First file task passed, per Windows screenshot | Extend to finding a moved document and verifying its contents |
| Skill selection by the live model | Pending | Model invokes the relevant skill during a successful task |
| Live follow-up | User screenshot shows a completed follow-up about the file | Broader continuation and recovery tasks remain to be tested |
| Browser behavior | Discovery passed; actions pending | A harmless page task succeeds with live DOM evidence |
| Portable Windows installer | Core and desktop setup/import checks passed on target | Standard full-Python installation path remains untested |
| Windows desktop / RDP | Softros task passed per user report | New cleanup/search behavior, popup, stop, lock and disconnect acceptance checks |
| TaxPrep / Profile | Not tested | Correct package from a test return under the firm's SOP |
| PandaDoc / Google Drive | Not tested | Authorized test account operations with actual destination evidence |
| Existing portal | Not integrated | Portal authentication, jobs, results and supported billing connected later |
| File download and usage UI | Chrome/API regression and desktop/mobile visual checks passed on Mac | Confirm 0.1.4 usage cards on Windows; full accessibility audit remains outside this check |

Do not interpret offline adapter tests, tool discovery or an HTTP 200 as evidence that an autonomous tax closeout works. The first Windows model task establishes basic file-tool execution; desktop and tax-workflow acceptance are the next milestones.

## Reproduce

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q clara scripts
node --check clara/static/app.js
node --test tests/test_chat_artifacts.mjs
bash -n Start-Clara.command Login-Clara.command Open-Clara.command scripts/install-mac.sh
.venv/bin/python scripts/probe-sdk.py
```

After sign-in, use `scripts/live-smoke.py` with the server stopped, or run the equivalent task in the dashboard. Connector discovery uses `scripts/probe-connectors.py` with the desired connectors enabled in Settings. The Windows checklist documents the remaining target-platform checks.
