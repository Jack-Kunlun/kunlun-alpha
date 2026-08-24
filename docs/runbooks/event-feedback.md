# Event Feedback Runbook

`POST /v1/event-feedback` and `GET /v1/event-feedback` are fail-closed. `EventFeedbackModule` uses
`DenyAllEventFeedbackAuthorizer` until an authenticated identity adapter is explicitly supplied; never replace it with an
allow-all production default. PostgreSQL requires `EVENT_FEEDBACK_POSTGRES_DSN` from secret storage.

Writes are append-only and idempotent by `reviewerRef + clientRequestId`. Reusing that identity with a different payload
returns conflict. The API derives reviewer, timestamps, feedback ID and submission fingerprint; clients cannot submit them.
Raw comments may contain sensitive text and must not appear in logs, metrics, screenshots or error messages.

Feedback is not automatically promoted to evaluation truth. Export only through the authorized filtered endpoint, perform
two-person evidence review and redaction, then create a new immutable dataset version as described in
`research/event-intelligence/README.md`.
