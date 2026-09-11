# Optional outbound portal adapter

The local dashboard remains bound to loopback. The worker initiates HTTPS requests to a configured portal every ten seconds; it never exposes Windows control over an unauthenticated network listener. The existing firm's portal must implement these endpoints. No production portal is connected by this source release.

Create `%LOCALAPPDATA%\Clara\portal.json` after reviewing the model account arrangement:

```json
{
  "enabled": false,
  "base_url": "https://your-portal.example",
  "worker_id": "rdp-operator-1",
  "owner_key": "operator-1",
  "token_env": "CLARA_PORTAL_TOKEN",
  "allow_autonomous": false,
  "authentication_reviewed": false
}
```

The token is supplied through that operator's environment, not stored in this JSON or committed. Native Claude login is not a portal token. Keep the worker owner fixed; each assignment must match that owner. Enabling is a deliberate deployment/configuration step. Restart Clara after configuring it. A shared client-facing product requires a supported authentication/billing arrangement; this adapter does not authorize subscription pooling.

`POST /v1/clara/claim` receives `worker_id` and `owner_key`, with an Authorization Bearer header. Return `{"assignment": null}` or a single assignment:

```json
{"assignment":{"id":"stable-business-assignment-id","owner_key":"operator-1","prompt":"Find the test engagement letter in the configured test folder and attach it.","mode":"ask"}}
```

Use stable IDs and immutable prompt/owner/mode. Repeated identical IDs refer to the existing job; changed content with the same ID is rejected. New claims occur only when there is no unacknowledged assignment and the local executor is idle. The portal should lease assignments and redeliver after network loss. Clara persists before enqueue; a process restart marks unfinished work interrupted instead of replaying it.

`POST /v1/clara/result` receives assignment/job IDs, current status, terminal flag, last assistant reply, SDK usage and artifact metadata (`id`, `name`, `size`). Make this endpoint idempotent by assignment/job. Return `{"acknowledged":true}` only after durably recording the terminal result. Clara retries result reporting until acknowledgement; it does not repeat the task. Ask/approval responses and file bytes are not transported by this first protocol: the operator handles those in the local dashboard or the separately scoped browser delivery workflow. Do not label an artifact as uploaded to the portal merely from its metadata.

Statuses include queued/running/waiting and terminal completed/needs_review/incomplete/failed/cancelled/interrupted. A terminal model run does not mean an approved workflow. The portal must display incomplete and needs_review accurately.

No redirect following, plaintext HTTP or credentials embedded in URLs are accepted. Transport errors retain local job state; error summaries omit tokens and response bodies. Use the server's authenticated logs to diagnose protocol failures.
