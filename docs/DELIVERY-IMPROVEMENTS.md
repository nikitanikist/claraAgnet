# Questions and delivery efficiency · 0.2.5

Questions now separate the decision from supporting information. The visible card contains a short question, brief context and optional choices; technical background lives under Show details. Every choice requires a click. Free-form answers remain available, including multiple lines and Ctrl/Cmd+Enter submission. Existing long questions retain all their text, paragraph breaks and normal body weight. No automatic summarizer removes decision context.

The agent receives instructions to ask only for missing information, honor the user's latest corrections, avoid repeated confirmations of already authorized actions and keep meaningful consequences visible. Model adherence needs a live test; the UI does not manufacture missing choices or rewrite old questions.

## Reducing avoidable work

- Evidence lookup returns a compact, paginated index instead of dozens of full tool outputs. Select a tool or evidence kind, then use get_evidence only for the needed record. This avoids oversized results and repeated embedded logs. Full evidence remains locally available and conversation-scoped.
- Windows verification and screenshot storage now recognize flattened and structured SDK response forms. Failed/malformed checks cannot become verified desktop evidence. Browser stale-element errors and tool failures remain visible even when the SDK strips the outer error flag.
- Connections & settings has Reasoning effort: Fast, Balanced, Thorough, Extra thorough or Maximum. Balanced maps to medium and is the default for missing preferences. It keeps the chosen model. More/less effort can change both latency and accuracy; compare representative runs before choosing a firm default.
- Runtime instructions favor small observations, supported locators/form tools, fresh element references after page changes and reuse of a successful method after verifying the current document and recipient. Important identity and output checks remain required.
- The memory tool advertises its accepted record kinds. The runtime requests reviewed procedures before rediscovery and sanitized candidate lessons after success. A saved chat/session or cookie is not automatic learning. Existing qualification and operator-review rules still apply.

## Time and cost

New final/partial usage reports include total elapsed time, waiting for the user and remaining working time. Waiting intervals include questions and approvals, are merged if overlapping, and end at cancellation/completion. Working time includes model, tool, network and other processing; it is not a direct inference measurement. CSV exports include both fields. Old reports remain unchanged when timing was not recorded. Request and workflow time limits still count wall time.

Token counts include repeated cached context across turns. The API estimate is not the subscription bill. See [usage interpretation and capacity measurement](USAGE.md).

## Repeat test on Windows

1. Finish or stop active work, update and restart Clara. Confirm LOCAL · 0.2.5.
2. Keep the intended model; choose Balanced effort for the first comparison. Existing source documents, outputs, sign-ins, history and edited skills are preserved.
3. Use a separate, clearly named test case/folder. For the same unfinished case, continue its saved conversation and inspect existing output/remote state first; do not repeat external writes just to benchmark speed.
4. Check that questions are short, necessary and readable. Reply through a choice or a multiline answer. Confirm the final usage card separates waiting time.
5. Compare the same task scope, verified output quality, model turns, working time and cache/input/output counts. Log in beforehand to avoid comparing authentication delays with execution time. Review recipient and field placement before accepting results.
6. Review any proposed procedure in Knowledge & memory; do not infer that a second run is faster until measured. Keep evidence of failed attempts as well as successful ones.

This release is a qualification candidate. Local regression tests do not establish a three-minute closeout, end-to-end production acceptance or a guaranteed subscription capacity.
