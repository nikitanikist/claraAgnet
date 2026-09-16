# Reviewed portal wire contract

Upstream snapshot before the local extension: nikitanikist/clearform-hub, commit 5e48f5c8a67a4dbc7e546e9f3a6d263a0302dc7a, `contracts/clara.contract.v1.json` (SHA-256 46dd0eb978d94c738165c8c3623e4286f26d64cd88dfa36044f9670b5dacd678).

SHA-256 of the file in this repository (with the local extension below): 21bb7fad081feff2205050661ad338222ccc9fd3ed771a00c41f8e0580b69f6c

This is an offline snapshot, not a network-fetched schema. Contract conformance does not establish server behavioral correctness or live acceptance. The v1 adapter is connected only on the development branch and is not enabled for Windows release. The finalization error is included; context delivery failure has exactly two valid release/hold outcomes. Generic recovery holds do not require context-only flags. Ambiguous receipts remain rejected and held.

Local extension, 16 September 2026: operation `clara-preview` (worker audience, non-idempotent) added for the
live desktop view; the portal repository must mirror it in `contracts/clara.contract.v1.json` (Lovable build
"Clara workspace v5"; cite that commit here once it lands). The heartbeat operation is unchanged, so a worker with this contract runs against a portal that
does not have the function yet (its preview loop backs off), and the portal change is purely additive.
