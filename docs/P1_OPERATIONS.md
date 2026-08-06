# P1 operations

## Worker jobs

From `apps/api`, run `uv run --env-file ../../.env python -m app.worker`. The worker claims `durable_jobs` with a lease and processes notification delivery, saved-search matching, calendar sync, CRM sync, brochure rendering, analytics aggregation, panorama validation and legal watermark integration points.

Inside the pre-synced container image, the equivalent command is `uv run --no-sync python -m app.worker`.

## Provider activation

- SMTP: set `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.
- Zalo OA: set `ZALO_ENDPOINT` and `ZALO_TOKEN` for the approved OA message endpoint.
- CRM: create a connection in `/admin/crm`; `local` validates staging, `webhook` POSTs idempotent payloads to the configured URL.

Blank provider configuration intentionally uses local delivery IDs. Production readiness requires provider-owned staging credentials and webhook signature verification.

## Scheduled jobs

A scheduler should enqueue:

- `saved_search_matching` every 15 minutes.
- `appointment_reminder` every hour.
- `analytics_aggregation` daily after midnight in Asia/Ho_Chi_Minh.
- legal expiry checks daily.

Jobs are idempotent and safe to enqueue more than once with an idempotency key.
