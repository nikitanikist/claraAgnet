# Clara 0.2.1 implementation and qualification

This release implements the local execution, browser, retrieval and workflow layer of the CPA plan. It is a **qualification candidate**. It is not evidence that an entire T1/T2 engagement has passed on the firm's Windows server.

## Available now

| Capability | Implementation | Practical boundary |
|---|---|---|
| Chrome | Pinned Chrome DevTools MCP, dedicated profile, per-page tools, file upload/download | Sign into actual websites in Clara's Chrome; no ordinary-profile cookie copying |
| Non-admin browser setup | Application-local Windows Node 22.22.3, official SHA-256 verification, locked npm dependencies | Windows policy must allow those executables; no elevation/policy changes |
| Windows observation | Fresh window/PID enumeration, foreground confirmation, app version lookup, bounded accessibility inspection | Native behavior still needs RDP testing |
| Windows actions | Up to six named UIA/shortcut actions with fresh focus checks and expected-control readback | Earlier actions may have occurred if a later action errors; inspect before retry |
| Business workflows | Persisted stage contracts, source copies, PDF evidence, remote readback, operator review | A model reply cannot approve a configured workflow; configure one before a serious task |
| Recovery | Tool observations and uncertain-action markers, checkpoints, source/output hashes, resume rechecks | No automatic replay after a crash; old remote/UI observations must be refreshed |
| Memory | Candidates, review, client/firm scopes, build filters, evidence-backed uses, suspension, 90-day expiry | Qualification records outcomes; it is not a formal proof that a particular shortcut caused the outcome |
| Knowledge | Eight libraries; source metadata; PDF/DOCX/Markdown/text import; bounded FTS retrieval by client/year/build | Sources shipped are an index, not downloaded manuals. Scanned PDFs require OCR text first |
| CPA guidance | 18 business skills, installed with edit-preserving version manifests | Skills are not tax certification; firm rules and real test cases remain necessary |
| External-write record | Stable scoped reservations; uncertain writes block replay; readback reconciliation and one operator-reviewed retry after confirmed absence | Guarantees apply to this ledger. Raw browser clicks/OS commands are not a transactional remote API |
| Costs | Per-run SDK usage plus workflow-wide turn/time/estimate accounting | API estimate is not the Max bill or remaining plan allowance; unknown usage stays unknown |
| Diagnostics | Local bounded text, tool timing, checkpoints, evidence checks and retained screenshots | Screenshots: up to 100 MB, seven-day pruning on new captures; text history remains local |
| Portal | Disabled-by-default outbound assignment/result adapter, durable deduplication, operator binding | Existing portal must implement the documented protocol; files and interactive questions still use the local dashboard |
| Update | Local consistent data backup, checked Git update, runtime refresh and documented restore | Windows PowerShell execution/rollback drill still require target validation |

## T1 contract

Use Workflow review to create **T1 print test** or **Full T1 closeout** before sending the task. Record an unambiguous client key, year and exact member names. A print test does not require invoicing or sending signatures. Full closeout requires:

1. Intake and source-copy hash evidence.
2. Live application identity observation.
3. Client copy, T183 and engagement letter for each member.
4. Verified PandaDoc record.
5. Verified billing record.
6. Verified storage and portal records.
7. Operator review of the package.

Required stages cannot be deleted by the model. A firm-approved scope that omits an invoice or changes required documents needs a corresponding reviewed contract change; this release does not silently waive a requirement. PDF checks establish readable text, identity/year, document markers, hash and minimum pages. They do not establish every expected form or correct tax treatment. The reviewer must check completeness and accounting conclusions. A browser readback checks observed fields, not legal validity or signature completion.

Generic accounting templates enforce order and evidence presence. Their detailed reconciliation and accounting acceptance criteria remain in firm procedures/review; the current engine cannot certify accounting correctness from generic evidence.

## Learning

Clara records a candidate with application/build, preconditions, actions and expected outcome. The operator reviews it and decides whether a sanitized procedure can be shared with the firm. Client facts cannot be promoted to firm scope. Reuse is marked qualified only after three evidence-backed uses, two different case identities and more than one conversation, with matching application build. A failure can suspend the lesson. No model tool can approve or publish its own memory. Old lessons expire for automatic reuse after 90 days.

The model weights are not retrained. This is persistent retrieval of procedures, evidence, preferences and scoped facts. A short successful method can reduce discovery time on the next run, but there is no promised three-minute closeout or fixed accuracy percentage.

## Connector choices

Chrome provides a working common route to PandaDoc, Microsoft 365, Google Drive, a web billing application and the portal. These services are not marked connected merely because Chrome launches. Native TaxPrep, ProFile, Caseware and desktop accounting products use Windows tools. Dedicated Graph, PandaDoc, QuickBooks and other API adapters are not shipped in this release; installing more wrappers without tenant authorization would not make them connected.

The optional portal adapter is for one configured operator. Its authentication arrangement needs review before deployment; this release does not pool or redistribute one Max subscription across other users. Native Claude login remains local and no paid API fallback is added.

## Production gate

Run [the qualification matrix](CPA-ACCEPTANCE.md), including actual RDP reconnect/lock behavior and the full closeout delivery chain. No tax return is filed merely to qualify the software. Record server/software builds, elapsed time, token categories, API estimate, expected and actual artifacts, exceptions and reviewer outcome for every case. Compare first-run and repeated-run performance on equivalent cases before reporting improvement to the client.
