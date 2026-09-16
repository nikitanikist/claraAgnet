# Reviewed portal wire contract

Upstream snapshot before the local extension: nikitanikist/clearform-hub, commit 5e48f5c8a67a4dbc7e546e9f3a6d263a0302dc7a, `contracts/clara.contract.v1.json` (SHA-256 46dd0eb978d94c738165c8c3623e4286f26d64cd88dfa36044f9670b5dacd678).

SHA-256 of the file in this repository (with the local extension below): 94e5f893d0bffc378d442f21a3db7911a4ebf295a03b7874dc8ed13f12262585

This is an offline snapshot, not a network-fetched schema. Contract conformance does not establish server behavioral correctness or live acceptance. The v1 adapter is connected only on the development branch and is not enabled for Windows release. The finalization error is included; context delivery failure has exactly two valid release/hold outcomes. Generic recovery holds do not require context-only flags. Ambiguous receipts remain rejected and held.

Correction, 16 September 2026: the empty claim window is now expressible. `clara_claim_next_job` hands a
closeout assigned with no chat input the window (`delivery_from_seq` 1, `message_boundary_seq` 0), which the
delivery code has always accepted as the `(1, 0)` special case, but both contract copies still declared a
minimum of 1 and the portal therefore refused its own claim and requeued it every few seconds. The minimum is
0 on `clara-claim.response.message_boundary_seq`, `clara-message-ack.request.acked_seq`,
`clara-message-ack.response.acked_seq` and `.to_seq`, and `clara-messages.response.to_seq`. `delivery_from_seq`
and `clara-messages.response.from_seq` still start at 1. No database change was needed: `clara_ack_messages`
already accepts an acknowledgement of 0 and reports the window complete.

Local extension, 16 September 2026: operation `clara-preview` (worker audience, non-idempotent) added for the
live desktop view; the portal repository must mirror it in `contracts/clara.contract.v1.json` (Lovable build
"Clara workspace v5"; cite that commit here once it lands). The heartbeat operation is unchanged, so a worker with this contract runs against a portal that
does not have the function yet (its preview loop backs off), and the portal change is purely additive.
