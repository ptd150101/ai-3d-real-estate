# P1 acceptance checklist

- [x] Notification outbox, in-app center, preferences, email/Zalo adapters, webhook delivery state, retry and idempotency.
- [x] Saved-search matching, price-drop detection, immediate/daily/weekly subscriptions and duplicate prevention.
- [x] Agent availability rules/exceptions, slot generation, atomic booking, status lifecycle and reminders integration.
- [x] Verified agent reviews, response, report/moderation and aggregate rating.
- [x] Persisted direct messaging, WebSocket delivery, idempotent client messages, receipts, typing and offline notification fallback.
- [x] CRM provider interface, local/webhook providers, lead dedupe, agent routing, mappings, retry and sync history.
- [x] Panorama scene graph, room links, hotspots, navigation zones, admin creation UI and browser viewer.
- [x] Cached PDF brochure with Unicode Vietnamese font, QR code and dynamic property Open Graph image.
- [x] Versioned private legal-document workflow, reviewer decisions, signed grants, expiration and download audit.
- [x] Versioned analytics events, PII stripping, dedupe, daily aggregation, funnel/viewer/AI/notification/CRM dashboards.
- [x] Durable job leases, heartbeats, exponential retry and dead-letter state.
- [x] PostgreSQL migration from P0, API tests, Next.js build, full-stack Docker and Playwright validation in CI.

Real SMTP, Zalo OA and third-party CRM delivery require the owner's provider credentials. The same production code paths have local deterministic adapters so tests never fabricate a vendor success response.
