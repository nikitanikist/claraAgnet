# Windows and CPA qualification matrix

Run on the actual non-admin Windows/RDP account with synthetic or explicitly designated test clients. This matrix is not marked passed by local unit tests. Capture the app version, Windows build, TaxPrep/ProFile build, session/resolution, model, skill revision and source hashes.

| Case | Required result |
|---|---|
| 01 Existing portable install update | Backup, core, desktop bridge probe and browser setup pass without elevation |
| 02 Browser alone | DOM snapshot, form fill, file upload/download and result readback succeed |
| 03 Desktop alone | Missing/disabled Chrome does not block a Windows task |
| 04 New TaxPrep window | Fresh list detects a process/window created after the previous observation |
| 05 Ambiguous windows | Two client windows require exact handle/PID; no silent title selection |
| 06 Focus refused | No text goes into another application's foreground window |
| 07 Unexpected popup | Inspect popup, recover using an observed action, retain evidence |
| 08 Moved source file | Targeted file search finds and verifies it without Explorer browsing |
| 09 Wrong year/member | PDF verifier rejects it; documents stage stays incomplete |
| 10 Empty/scanned output | Missing readable content is flagged; it is not declared a valid return |
| 11 T1 single member | Correct selected client forms, T183 and engagement package are printed and inspected |
| 12 T1 household | Every requested member has their own correct documents and signer mapping |
| 13 Changed output after checkpoint | Hash recheck blocks reuse of outdated evidence |
| 14 Repeated printing recovery | Verified method is proposed; candidate not immediately auto-qualified |
| 15 Memory qualification | Review plus three uses across two cases and a fresh conversation; exact build matching |
| 16 Duplicate PandaDoc/upload/invoice | Stable ledger key blocks replay; actual remote state reconciled after timeout |
| 17 Full closeout chain | Documents, PandaDoc draft, approved invoice, storage, portal and operator review all evidenced |
| 18 Cancel/restart/turn limit | Saved incomplete state, usage and uncertain writes survive; no automatic replay |
| 19 RDP reconnect/lock/resolution | Observe behavior on this server; stop if input desktop unavailable; no blind coordinates |
| 20 Backup/restore and repeated-run timing | Restore downloads/skills/history in test data; compare equivalent runs and aggregate tokens/cost |

Before case 17, the firm supplies actual template/recipient rules, invoice fees and tax treatment, storage paths, portal status mapping and the designated reviewer. Use drafts unless sending is explicitly part of the test. T1 closeout is separate from CRA transmission.

For each case record: expected artifacts, actual hash/page/remote-ID evidence, failures, elapsed seconds, model turns, input/output/cache tokens, reported API estimate, reviewer and decision. Do not use a synthetic fixture's costs as the price of a real closeout. A repeated task should be compared on equivalent inputs; report median and slow cases rather than one best run.

Start with the print-only workflow. Example task after entering the client/year/member in Workflow review:

> Use the CPA T1 closeout skill for the configured print test. Find the matching source under my configured test folder, create and verify a working copy, inspect the actual TaxPrep build and client window, print the requested client copy, verify its PDF, save stage evidence and attach a handoff. Do not send, invoice or file anything. Use relevant documentation and qualified memory; propose a lesson if you discover a successful recovery.

If the run stops, export its diagnostics and continue in the same conversation after reviewing the saved stage and budget. Incomplete usage cannot be treated as zero; review the failed run before starting another billable attempt.
