# P2 implementation roadmap

## 1. Baseline and definition of done

P0 and P1 are merged into `main` at commit `1842ba70196b7fd1483ca55cda4f4c9e55ac6669`. P2 extends that validated foundation rather than replacing it.

P2 is complete only when every enabled epic has:

- persisted PostgreSQL models and reversible Alembic migrations;
- authenticated and authorized API surfaces;
- production UI for public, buyer, agent, agency and platform-admin roles;
- durable background jobs with idempotency, retry and dead-letter behavior;
- audit logs, observability and privacy controls;
- unit, integration, PostgreSQL migration, Docker and Playwright coverage;
- feature flags and safe rollback;
- one validated provider path on staging where an external provider is required;
- no feature represented only by a mock, static placeholder or fabricated provider response.

Real payment, identity, signature and communication vendors require owner-supplied contracts and credentials. P2 must keep provider-neutral domain models and deterministic local adapters for CI.

## 2. P2 product scope

P2 contains ten product epics plus one release-hardening epic:

1. Multi-agency marketplace and tenant administration.
2. Reservation payments, refunds and financial reconciliation.
3. Contract generation and electronic-signature workflows.
4. Automated valuation model (AVM).
5. Advanced recommendation and ranking engine.
6. Image/video-to-3D reconstruction pipeline.
7. Augmented-reality property and furniture placement.
8. Immersive VR property tours.
9. Native mobile application.
10. ML/GPU platform, experimentation and cost governance.
11. Security, compliance, load testing and staged rollout.

## 3. Architectural principles

- Keep `properties`, `agents`, `agencies`, leads, appointments and conversations as the system of record.
- Add organization scoping without breaking current single-agency data.
- Treat money movement as a state machine backed by immutable ledger entries.
- Never describe a payment flow as escrow unless the legal and provider arrangement explicitly supports it.
- Treat electronic signing as document execution, not automatic legal transfer of land-use or ownership rights.
- Separate model training from online inference.
- Store model version, feature version and input snapshot for every AI result.
- Return uncertainty, comparables and explanations with every valuation.
- Build recommendation retrieval and ranking as separate stages.
- Keep original captures, reconstructed assets and optimized delivery assets separately versioned.
- Prefer progressive enhancement: gallery and panorama must remain available when AR, VR or WebGL is unavailable.
- Gate every high-cost or high-risk feature behind agency- and user-level feature flags.

## 4. Epic P2-01 — Multi-agency marketplace

### Goal

Turn the current application into a platform where multiple agencies can onboard, manage teams, publish inventory and operate with isolated data and configurable commercial rules.

### Data model

- `organizations`
- `organization_members`
- `organization_invitations`
- `organization_roles`
- `organization_feature_flags`
- `marketplace_plans`
- `organization_subscriptions`
- `listing_quotas`
- `platform_commission_rules`
- `agency_verification_cases`
- `agency_domains`
- `tenant_audit_exports`

Existing `agencies` become marketplace business profiles linked one-to-one to an organization. Existing records are migrated into a default organization.

### Backend

- organization-scoped authorization dependency;
- role matrix for owner, manager, agent, reviewer, finance and analyst;
- invitations, membership lifecycle and domain verification;
- plan/feature entitlement service;
- listing quotas and overage events;
- agency verification workflow;
- tenant-safe query helpers and mandatory scoping tests;
- platform-admin impersonation with explicit reason and audit record;
- tenant data export and deletion workflows.

### Frontend

- `/agency/onboarding`;
- `/agency/settings/team`;
- `/agency/settings/roles`;
- `/agency/settings/billing`;
- `/agency/settings/domains`;
- `/platform/agencies` and verification queue;
- organization switcher for users belonging to multiple agencies;
- quota, plan and usage surfaces.

### Acceptance

- no cross-tenant read or write is possible through API, WebSocket, signed URL or background job;
- current P0/P1 records migrate without loss;
- agency owner can invite, suspend and change roles;
- feature flags and quotas are enforced server-side;
- tenant export is complete and reproducible;
- platform-admin impersonation is time-limited and audited.

Estimated effort: 10–14 working days.

## 5. Epic P2-02 — Reservation payments and reconciliation

### Goal

Allow a buyer to pay a configurable reservation or service fee while preserving accurate financial state, refunds and reconciliation.

### Data model

- `payment_provider_accounts`
- `reservation_orders`
- `payment_intents`
- `payment_transactions`
- `payment_webhook_events`
- `refund_requests`
- `refund_transactions`
- `payment_disputes`
- `ledger_accounts`
- `ledger_entries`
- `settlement_batches`
- `reconciliation_runs`

### State machines

Reservation:

`draft -> awaiting_payment -> paid -> confirmed -> completed`

Alternative exits:

`expired`, `cancelled`, `refund_pending`, `refunded`, `partially_refunded`, `disputed`, `failed`.

### Backend

- provider-neutral `PaymentProvider` interface;
- VNPAY sandbox adapter as the Vietnam-first reference integration;
- optional Stripe Connect adapter for supported marketplace deployments;
- signed webhook verification and replay protection;
- idempotent payment creation, callback and refund processing;
- immutable double-entry ledger;
- expiration and inventory lock jobs;
- reconciliation against provider transaction-query APIs;
- refund approval workflow and reason codes;
- downloadable receipts and finance audit export;
- configurable commission and fee calculation.

### Frontend

- reservation checkout;
- payment return/cancel pages;
- buyer payment history;
- agent reservation status;
- finance dashboard, refunds and reconciliation exceptions;
- clear disclosure of what the payment reserves and the refund policy.

### Acceptance

- duplicate callbacks cannot duplicate money or reservations;
- ledger balances remain balanced for every transaction;
- provider and local status can be reconciled after outages;
- expired payments release the property reservation lock;
- refund workflow is fully audited;
- no card data is stored by Nestora;
- chaos tests cover delayed, duplicated and reordered webhooks.

Estimated effort: 12–16 working days plus provider onboarding.

## 6. Epic P2-03 — Contracts and electronic signatures

### Goal

Generate versioned documents from verified transaction data, route them to signers and retain evidence without claiming that every real-estate instrument is legally executable online.

### Data model

- `contract_templates`
- `contract_template_versions`
- `contract_envelopes`
- `contract_documents`
- `contract_participants`
- `signature_requests`
- `signature_events`
- `signature_evidence`
- `contract_amendments`
- `contract_void_events`

### Backend

- template variables with allowlisted fields;
- server-side PDF rendering and immutable checksum;
- `SignatureProvider` interface with local and external adapters;
- embedded and remote signing modes;
- signer identity and consent evidence;
- webhook event verification and event ordering;
- envelope expiration, reminder, void and correction flows;
- signed-document private storage and access grants;
- legal-review flags by document type and jurisdiction;
- retention and deletion policy.

### Frontend

- contract template editor and preview;
- transaction data review before envelope creation;
- signer progress timeline;
- embedded signing handoff;
- download signed evidence bundle;
- amendment and void workflow.

### Acceptance

- signed bytes and checksums cannot be silently replaced;
- every signer action has timestamp, provider ID and evidence metadata;
- duplicate/out-of-order webhooks converge to the correct state;
- restricted document types cannot be sent without legal approval;
- access is tenant-scoped and time-limited;
- legal counsel signs off the supported-document matrix before production rollout.

Estimated effort: 10–14 working days plus legal/provider review.

## 7. Epic P2-04 — Automated valuation model

### Goal

Estimate a supported property segment's market value with uncertainty, comparable listings and transparent model/version metadata.

### Data model

- `valuation_datasets`
- `valuation_dataset_versions`
- `valuation_features`
- `valuation_model_versions`
- `valuation_training_runs`
- `valuation_evaluations`
- `valuation_requests`
- `valuation_results`
- `valuation_comparables`
- `valuation_overrides`
- `valuation_drift_metrics`

### Pipeline

1. Ingest verified historical transactions and listing observations.
2. Normalize address, time, area, property type and legal attributes.
3. Generate spatial, temporal, project, amenity and market features.
4. Train segmented baselines and tree-based models.
5. Calibrate prediction intervals.
6. Evaluate by time split, geography and property segment.
7. Register an approved model.
8. Serve online inference with feature snapshots.
9. Monitor drift, error and override feedback.

### API and UI

- `POST /valuations`;
- `GET /valuations/{id}`;
- agency bulk valuation;
- property price guidance in admin;
- result card containing range, confidence, comparable properties and caveats;
- analyst model registry, evaluation and drift dashboard;
- human override with reason and retained original prediction.

### Acceptance

- the production model must beat the declared heuristic baseline on a time-based holdout;
- metrics are reported separately by district and property type;
- every result includes model version, feature timestamp, interval and comparable evidence;
- unsupported or out-of-distribution properties return `insufficient_data`, not a confident estimate;
- no protected or irrelevant personal data is used;
- drift alerts can disable automated display without redeploying.

Estimated effort: 15–22 working days after data access is secured.

## 8. Epic P2-05 — Recommendation and ranking engine

### Goal

Personalize discovery while preserving relevance, diversity, freshness and user control.

### Data model

- `recommendation_profiles`
- `recommendation_feature_snapshots`
- `recommendation_candidates`
- `recommendation_impressions`
- `recommendation_feedback`
- `ranking_model_versions`
- `recommendation_experiments`
- `experiment_assignments`

### Architecture

- candidate sources: saved searches, content similarity, collaborative signals, popularity, location and agent-curated sets;
- retrieval using SQL/PostGIS/pgvector;
- ranking service using user, property, context and freshness features;
- diversity and business-rule post-processing;
- explicit controls to reset personalization and hide a property;
- offline training and online low-latency inference;
- anonymous cold-start profile before login;
- A/B experiment framework connected to P1 analytics.

### Surfaces

- personalized home feed;
- similar properties;
- "because you viewed/saved" explanations;
- next-best property in chatbot;
- agent lead recommendations;
- notification ranking for saved-search digests.

### Acceptance

- offline NDCG/Recall and online click/save/appointment metrics beat the non-personalized baseline;
- duplicate, unavailable and already-dismissed properties are excluded;
- results meet configured diversity and freshness constraints;
- users can disable/reset personalization;
- experiment assignment is stable and auditable;
- recommendation failure falls back to deterministic search.

Estimated effort: 12–18 working days.

## 9. Epic P2-06 — Image/video-to-3D reconstruction

### Goal

Convert compliant capture sets into reviewable 3D assets while preserving the existing manually uploaded GLB path.

### Data model

- `capture_sessions`
- `capture_requirements`
- `capture_files`
- `capture_quality_reports`
- `reconstruction_jobs`
- `reconstruction_stages`
- `reconstruction_artifacts`
- `asset_optimization_jobs`
- `generated_asset_reviews`
- `gpu_worker_pools`

### Pipeline

1. Guided capture creates an upload manifest.
2. Validate blur, exposure, overlap, orientation and coverage.
3. Run camera reconstruction using COLMAP-compatible structure-from-motion.
4. Produce one or more representations:
   - Gaussian splat for photorealistic walkthrough;
   - mesh/point cloud for editing and fallback;
   - optimized GLB for web/AR where quality permits.
5. Crop, align scale and orient floors.
6. Generate preview, thumbnails and quality report.
7. Human reviewer approves or rejects.
8. Optimize and publish versioned delivery assets.

### Infrastructure

- separate GPU worker image and queue;
- resumable stage checkpoints;
- per-stage timeout and cost accounting;
- local development adapter with small fixture;
- encrypted/private original captures;
- lifecycle deletion for raw captures;
- model/license manifest for every generated artifact.

### Acceptance

- incomplete or low-quality captures fail with actionable guidance;
- retries resume from the latest valid stage;
- generated assets never auto-publish without review;
- scale/orientation metadata is retained;
- output is versioned and reversible;
- browser fallback remains available when splats are unsupported;
- GPU cost and processing duration are visible per job.

Estimated effort: 20–30 working days and GPU infrastructure.

## 10. Epic P2-07 — Augmented reality

### Goal

Allow supported mobile users to place a property model, room model or furniture object in their environment with correct scale and safe fallbacks.

### Data model

- `ar_assets`
- `ar_asset_variants`
- `ar_placement_profiles`
- `ar_calibration_records`
- `ar_sessions`
- `ar_compatibility_reports`

### Implementation

- web AR adapter based on GLB plus iOS-compatible asset variant;
- WebXR, Android Scene Viewer and iOS Quick Look launch modes;
- real-world scale validation and configurable placement mode;
- floor/wall placement profiles;
- dimension overlay and placement reset;
- AR entry from property, room and furniture hotspot;
- device-capability detection and analytics;
- static 3D fallback when AR is unsupported;
- admin asset compatibility preview.

### Acceptance

- scale error is within the accepted tolerance on the supported device matrix;
- Android and iOS fallback paths are tested separately;
- unsupported devices never show a dead AR button;
- no camera image is uploaded without explicit user action;
- AR session failures are observable by browser/device;
- asset variants remain linked to the same source model version.

Estimated effort: 10–14 working days after suitable assets exist.

## 11. Epic P2-08 — Immersive VR tours

### Goal

Provide comfortable immersive tours on supported headsets using panorama, GLB and optionally Gaussian-splat assets.

### Data model

- `vr_tour_configs`
- `vr_navigation_nodes`
- `vr_device_profiles`
- `vr_sessions`
- `vr_performance_samples`

### Implementation

- WebXR immersive-VR capability detection;
- teleport navigation and snap turning;
- seated/standing modes;
- controller ray interaction for hotspots and floor changes;
- comfort vignette and motion-speed limits;
- panorama fallback for low-performance devices;
- spatial audio as an optional asset;
- synchronized property facts and chatbot panels outside immersive mode;
- kiosk mode for sales offices.

### Acceptance

- no forced smooth locomotion;
- stable frame-rate budget is defined per supported device class;
- users can exit immersive mode at all times;
- controller, gaze and keyboard fallback paths are tested;
- unsupported browsers retain the normal 3D/panorama experience;
- session performance and failure reasons are recorded without storing sensitive sensor data.

Estimated effort: 12–18 working days.

## 12. Epic P2-09 — Native mobile application

### Goal

Deliver buyer and agent workflows through iOS and Android while reusing domain APIs rather than duplicating business logic.

### Architecture

- Expo/React Native application in `apps/mobile`;
- Expo Router navigation and deep links;
- generated API client from OpenAPI;
- secure token storage and refresh flow;
- push notifications mapped to P1 notification events;
- shared design tokens and contracts package;
- native map and camera/upload modules;
- AR launch/deep-link integration;
- EAS build profiles for development, preview and production.

### Buyer scope

- search/map/property details;
- favorite, compare and saved search;
- appointments, messages and notifications;
- reservation checkout handoff;
- panorama/3D with AR launch;
- offline cache for saved properties and recent conversations.

### Agent scope

- lead inbox and realtime messages;
- appointment calendar;
- capture-session guide and resumable upload;
- listing status and analytics summary;
- push notification actions.

### Acceptance

- deep links open the correct property, conversation or appointment;
- auth tokens are not stored in plain application storage;
- offline mutations queue safely and do not duplicate on reconnect;
- push notification permission and preference states remain synchronized;
- accessibility and crash-free-session targets are monitored;
- store privacy declarations match actual data collection.

Estimated effort: 20–28 working days.

## 13. Epic P2-10 — ML/GPU platform and experimentation

### Goal

Operate valuation, ranking and reconstruction workloads with reproducibility, cost visibility and safe promotion.

### Components

- model/artifact registry;
- dataset and feature versioning;
- offline training jobs;
- GPU/CPU worker capabilities and queue routing;
- experiment tracking;
- evaluation gates before model promotion;
- canary and shadow inference;
- cost budgets and per-tenant usage metering;
- drift, latency and failure dashboards;
- automated rollback to the last approved model;
- data-retention and deletion propagation into training datasets.

### Acceptance

- every online inference can be traced to model, code and feature versions;
- unapproved models cannot receive production traffic;
- reconstruction and training jobs enforce tenant quotas and cost limits;
- deleting a user's eligible data propagates to future datasets;
- model rollback does not require an application redeploy;
- evaluation reports are stored and reviewable.

Estimated effort: 12–18 working days, partly parallel with P2-04 to P2-06.

## 14. Epic P2-11 — Release hardening

- threat model for marketplace, payment, signature, ML and capture flows;
- tenant-isolation penetration tests;
- payment webhook chaos tests and ledger invariants;
- signed-document evidence and retention review;
- model abuse, prompt injection and data poisoning tests;
- GPU job sandboxing and malicious-file handling;
- load tests for search, recommendation, messaging and checkout;
- mobile device matrix and app-store preflight;
- AR/VR compatibility matrix;
- backup/restore including private documents and financial ledger;
- staged rollout by agency and feature flag;
- incident runbooks and kill switches.

Estimated effort: 10–15 working days.

## 15. Migration sequence

- `0003_organizations_and_entitlements`
- `0004_reservations_payments_and_ledger`
- `0005_contracts_and_signatures`
- `0006_valuation_registry_and_results`
- `0007_recommendations_and_experiments`
- `0008_capture_and_reconstruction`
- `0009_ar_vr_experiences`
- `0010_mobile_devices_and_push`
- `0011_mlops_usage_and_costs`

Each migration must upgrade from a production-shaped P1 fixture, support downgrade where data loss is not inherent, use indexes and constraints explicitly, and be exercised on PostgreSQL/PostGIS/pgvector in CI.

## 16. Delivery order and dependencies

### Phase A — Platform foundation, weeks 1–4

- P2-01 organization tenancy and entitlements.
- P2-10 model/job registry foundation.
- Provider and legal discovery for payments/signatures.

Exit gate: current data migrated, tenant-isolation suite green, feature flags operational.

### Phase B — Transaction layer, weeks 5–8

- P2-02 reservation payments.
- P2-03 contracts/signatures.

Exit gate: sandbox payment, refund, reconciliation and local/external signature adapter tests pass.

### Phase C — Intelligence, weeks 9–14

- P2-04 valuation MVP for one supported segment.
- P2-05 recommendation retrieval/ranking.

Exit gate: models beat declared baselines, explanations and fallback paths are validated.

### Phase D — Spatial computing, weeks 15–21

- P2-06 reconstruction pipeline.
- P2-07 AR.
- P2-08 VR.

Exit gate: reviewed generated asset can be published and opened through web, AR and VR fallback matrix.

### Phase E — Mobile, weeks 18–24

- P2-09 mobile app can run in parallel after stable organization/auth contracts exist.

Exit gate: preview builds pass buyer and agent end-to-end flows.

### Phase F — Hardening and staged release, weeks 25–27

- P2-11 security, performance, recovery and rollout.

Full-time estimate: 24–30 weeks for a small team. At approximately 20 hours/week for one engineer, expect 45–60 weeks unless epics are reduced or parallel contributors are added.

## 17. Pull-request strategy

Do not implement all of P2 in one PR. Suggested sequence:

1. `p2-01-tenant-foundation`
2. `p2-02-entitlements-and-agency-onboarding`
3. `p2-03-payment-domain-and-ledger`
4. `p2-04-vnpay-sandbox-and-reconciliation`
5. `p2-05-contract-domain-and-local-signing`
6. `p2-06-external-signature-adapter`
7. `p2-07-ml-registry-and-datasets`
8. `p2-08-valuation-baseline`
9. `p2-09-recommendation-retrieval`
10. `p2-10-recommendation-ranking-and-experiments`
11. `p2-11-capture-and-quality-validation`
12. `p2-12-reconstruction-workers`
13. `p2-13-ar`
14. `p2-14-vr`
15. `p2-15-mobile-foundation`
16. `p2-16-mobile-buyer-agent-flows`
17. `p2-17-release-hardening`

Every PR must include migration tests, role/tenant authorization tests, API contract updates, UI states, observability and rollback notes.

## 18. Go/no-go checklist

P2 is not 100% until all selected production epics satisfy the following:

- [ ] Multi-agency data isolation is independently tested.
- [ ] Reservation payment is idempotent and ledger-balanced.
- [ ] Refund and reconciliation work after provider outages.
- [ ] Supported contract types have legal approval and evidence retention.
- [ ] Valuation beats the baseline and returns calibrated uncertainty.
- [ ] Recommendations beat the baseline and respect user controls.
- [ ] Reconstruction jobs are resumable, review-gated and cost-metered.
- [ ] AR passes the supported Android/iOS matrix with correct scale.
- [ ] VR meets comfort and performance budgets.
- [ ] Mobile preview builds pass buyer and agent end-to-end tests.
- [ ] Models and datasets are versioned and reversible.
- [ ] Full PostgreSQL migration from P1 passes.
- [ ] Docker, browser, mobile and provider-sandbox CI are green.
- [ ] Backup/restore, incident response and feature kill switches are rehearsed.
- [ ] No external-provider capability is claimed without staging evidence.
