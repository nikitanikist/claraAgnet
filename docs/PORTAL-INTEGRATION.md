# Connecting the existing Clearhouse portal later

No existing portal code or production runner has been modified. The current application is one person's local workspace assistant.

## Already available locally

- Create/list conversations: `/api/conversations`
- Submit a task: `/api/conversations/{id}/messages` with `text`, `mode` and attachment IDs
- Stream durable events: `/api/conversations/{id}/events`, supporting event cursors
- Inspect jobs/files/pending questions: `/api/conversations/{id}`
- Upload references: `/api/conversations/{id}/upload`
- Answer a question or approve one action: `/api/requests/{id}`
- Stop work: `/api/jobs/{id}/stop`
- Download a published file: `/api/files/{id}`
- Manage skills and local settings: `/api/skills`, `/api/settings`

These endpoints intentionally require the local dashboard session. They are not ready to expose directly to the internet or call from an unrelated hosted portal origin.

## Decisions for the integration session

1. Read the portal's current authentication and closeout/job schema. Map authorized portal users to worker assignments and conversations.
2. Choose the approved inference account/billing arrangement for portal users. Do not route an entire firm through the developer's personal Max login.
3. Define the worker connection. Prefer an authenticated outbound worker channel/poll from RDP, with short-lived scoped job authorization, rather than opening a public desktop-control port.
4. Map attachments and results through authenticated storage. Preserve client/task provenance and restrict each user's access.
5. Map tool events, questions, approvals, interruption and result states into the portal UI. Preserve explicit distinctions between queued, running, waiting, completed, failed and interrupted.
6. Add the firm's verified SOPs, expected output checks, external-write identities and duplicate detection. Reuse existing scripts only where they are useful optional tools.
7. Validate a complete synthetic closeout on Windows before real client work.

The local chat UI can become a worker diagnostics/admin interface, while the existing portal supplies the staff-facing experience. The SDK loop and general tools can remain behind the worker boundary.
