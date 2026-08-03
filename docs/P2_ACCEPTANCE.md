# P2 production-build acceptance

P2 is complete at the **source-code and sandbox production-build validation** level only when every gate below is green on the same Git commit. Real merchant settlement, regulated e-signature, app-store publication and physical-device certification remain owner/vendor activities and are not source-code tasks.

## Functional scope

- [x] Multi-agency organizations, memberships, roles, feature entitlements, quota and tenant export.
- [x] Tenant scoping on P2 APIs and existing property, appointment and lead administration paths.
- [x] Reservation state machine, local/VNPAY/Stripe adapters, signed callback processing, refunds, reconciliation and balanced immutable ledger.
- [x] Versioned contract templates, legal policy gate, PDF generation, signer events, expiry/reminders and immutable evidence checksum.
- [x] Valuation with range, comparables, model/feature lineage, evaluation gate, override and drift kill switch.
- [x] Recommendation retrieval/ranking, explanations, hide/reset and personalization opt-out.
- [x] Capture validation, multipart private upload, resumable reconstruction job, artifact review and AR/VR delivery configuration.
- [x] Expo mobile capture flow for selecting a tenant/property, collecting 12–60 images, uploading each private image, creating a reconstruction job and polling its progress.
- [x] Expo mobile application with secure token storage, rotating refresh token, deep links, push registration, map and offline mutation dedupe.
- [x] ML artifact/model registry, evaluation gate, deployment, health check, canary traffic, rollback and CPU/GPU queue separation.
- [x] Real legacy media jobs: GLB/glTF validation and optional optimization, image thumbnail generation, knowledge indexing, panorama validation and legal PDF watermarking.
- [x] Agency UI for reconstruction review/rerun and ML deployment health/rollback; buyer UI renders structured valuation and recommendation output.
- [x] Feature kill switches, audit/export surfaces and deterministic local providers for CI.

## Required CI evidence

The PR may be marked ready only when all jobs pass:

- `api`: compile, P0/P1/P2 tests, multipart capture completion tests, media-worker tests, OpenAPI and SQLite migration cycle.
- `postgres-migration`: PostGIS + pgvector database, P1→P2 upgrade and P2 downgrade/upgrade rehearsal.
- `web`: TypeScript and Next.js production build, including reconstruction/MLOps operational consoles.
- `mobile`: Expo dependency check, TypeScript and Android export bundle, including the multi-image capture client.
- `compose`: default and GPU profile validation.
- `e2e`: full Docker stack, worker, smoke tests and Playwright P0/P1/P2.
- `backup-restore`: PostgreSQL dump, destructive marker, restore and integrity verification.
- `security`: dependency audits, Bandit, CodeQL, Gitleaks and Trivy.

## External production sign-off

The following are implemented as production adapters but cannot be represented honestly by a green CI fixture. They require owner-supplied accounts, contracts, credentials, data or devices:

- VNPAY/Stripe merchant credentials and provider reconciliation certification.
- Approved electronic-signature provider and legal review of each document type.
- EAS/APNs/FCM credentials and Google Play/App Store review.
- Supported ARCore/ARKit/headset device matrix.
- Production GPU pool running pinned COLMAP/Nerfstudio builds and licensed model artifacts.
- Production training/evaluation datasets and business approval of model quality thresholds.
- Staging recovery rehearsal for the configured private object-storage provider.

These items are deployment and certification work, not missing source-code implementations.
