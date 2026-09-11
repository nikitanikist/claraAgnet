# Current validation: 0.2.0 · 12 September 2026

- **71 Python tests pass**, including prior functionality and new workflow completion gates, wrong-client/stale-PDF rejection, checkpoint order, persistence, copy non-overwrite, aggregate resume budgets, incomplete usage, scoped/versioned memory qualification, suspension, uncertain external-write deduplication, portal assignment deduplication/owner binding, edit-preserving skills, authenticated operator APIs, PDF reference import, screenshot evidence masking/options, independent connector availability, owned-runtime update and SQLite/file backup/restore.
- **Real Chrome MCP smoke test passes** on an isolated local page: launch, DOM snapshot, field fill, upload, click and result readback. Its download-link action passes; actual download bytes are independently checked in the dashboard browser test. No client tenant or model was used.
- **Real Chrome/API UI regression passes**: artifact/CSV downloads, history/streaming, usage display, escaping, mobile layout, reference import, T1 workflow creation, rejected premature review and budget update. Screenshots were inspected locally.
- Pinned Chrome dependency installation, Python dependency check, source compilation and JavaScript parsing pass. Eighteen CPA skill files pass the skill validator. The real SDK/CLI protocol connects without a prompt; MCP startup may be deferred.
- The native Claude SDK account on this Mac is not signed in. **No fresh live-model inference is claimed for 0.2.0.** Earlier Windows live-model results remain historical evidence, not validation of every new feature.
- The Windows bridge wraps pinned Windows-MCP 0.8.5; its API paths were reviewed against that package. Import/probe and actual Windows focus/UIA/TaxPrep operations require the non-admin RDP acceptance run. PowerShell setup and rollback execution have not been run on Windows for this release.
- Portal transport is disabled by default. Unit tests verify local assignment semantics; actual authenticated portal endpoints, identity arrangement, file delivery and firm account connections still need integration. Dedicated vendor APIs are not implemented; Chrome supplies the UI route.
- PDF validation is identity/text/hash evidence, not tax correctness or full visual completeness. Memory qualification is reviewed outcome evidence, not a proof of causal shortcut correctness. Raw OS/browser actions are not a transactional API. Complete closeout time/cost, repeated-run improvement and production acceptance remain unmeasured.

One upstream Starlette/AnyIO test-client deprecation warning remains. No test failure remains in the recorded run.

---

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

## Release 0.1.5: desktop observation and run diagnostics

- 50 Python tests pass. Added cases exercise the actual SDK adapter hooks with a test double, normalization of empty observations while preserving useful UIA/image requests, structured and plain connector errors, bounded text retention without image bytes, clear exhausted-turn failures, and authenticated task-scoped log export.
- The Chrome/API regression covers expandable failed-tool text and timing, safe rendering of HTML-like tool output, real task-log and CSV downloads, saved history, usage/file cards and mobile layout. These fixtures do not invoke a model or Windows.
- Dependency versions and installer requirements are unchanged. The configured model and max-turn setting are preserved. Existing user-edited skills are not overwritten.
- The reviewed Windows history is evidence of a failed pre-print run, not a successful T1 closeout. We cannot recover missing tool output/screenshots from that older database or distinguish all model/network/SDK delays from event timestamps alone.
- Live Windows acceptance of this update, printing correctness, checkpoint quality and any speed improvement remain pending.
