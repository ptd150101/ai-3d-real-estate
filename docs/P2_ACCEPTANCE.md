# P2 production-build acceptance

P2 is complete at the **code and sandbox production-build validation** level only when every gate below is green on the same Git commit. Real merchant settlement, regulated e-signature, app-store publication and physical-device certification remain owner/vendor activities.

## Functional scope

- [x] Multi-agency organizations, memberships, roles, feature entitlements, quota and tenant export.
- [x] Tenant scoping on P2 APIs and existing property, appointment and lead administration paths.
- [x] Reservation state machine, local/VNPAY/Stripe sandbox adapters, signed callback processing, refunds, reconciliation and balanced immutable ledger.
- [x] Versioned contract templates, legal policy gate, PDF generation, signer events, expiry/reminders and immutable evidence checksum.
- [x] Valuation with range, comparables, model/feature lineage, evaluation gate, override and drift kill switch.
- [x] Recommendation retrieval/ranking, explanations, hide/reset and personalization opt-out.
- [x] Capture validation, resumable reconstruction job, artifact review and AR/VR delivery configuration.
- [x] Expo mobile application with secure token storage, rotating refresh token, deep links, push registration, map, offline mutation dedupe and capture guide.
- [x] ML artifact/model registry, evaluation gate, deployment, rollback and CPU/GPU queue separation.
- [x] Feature kill switches, audit/export surfaces and deterministic local providers for CI.

## Required CI evidence

The PR may be marked ready only when all jobs pass:

- `api`: compile, P0/P1/P2 tests, OpenAPI and SQLite migration cycle.
- `postgres-migration`: PostGIS + pgvector database, P1→P2 upgrade and P2 downgrade/upgrade rehearsal.
- `web`: TypeScript and Next.js production build.
- `mobile`: Expo dependency check, TypeScript and Android export bundle.
- `compose`: default and GPU profile validation.
- `e2e`: full Docker stack, worker, smoke tests and Playwright P0/P1/P2.
- `backup-restore`: PostgreSQL dump, destructive marker, restore and integrity verification.

## External production sign-off

These cannot be represented by a green CI fixture and require owner-supplied resources:

- VNPAY/Stripe merchant credentials and provider reconciliation certification.
- Approved electronic-signature provider and legal review of each document type.
- EAS/APNs/FCM credentials and Google Play/App Store review.
- Supported ARCore/ARKit/headset device matrix.
- Production GPU pool running COLMAP/Nerfstudio and licensed model artifacts.
