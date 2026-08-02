# P2 production integrations

This overlay separates deterministic CI fixtures from live production execution. In `ENVIRONMENT=production`, startup rejects local signing, fixture reconstruction, weak secrets, HTTP site URLs and missing DocuSign/S3 configuration.

## Payments

- **Stripe**: configure `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`; send raw events to `/api/v1/payments/webhooks/stripe`.
- **VNPAY**: configure `VNPAY_TMN_CODE`, `VNPAY_HASH_SECRET`, payment/API URLs and return URL; send IPN data to `/api/v1/payments/webhooks/vnpay`.
- Checkout, webhook processing and refunds use provider idempotency keys.
- Webhook amount/currency are matched against the locked local intent.
- `/api/v1/finance/reconcile?provider=...` queries provider state instead of comparing only local rows.
- Ledger rows are protected by database triggers against update/delete.

Live validation checklist:

1. Create a low-value reservation in each provider sandbox.
2. Replay the same webhook and verify no duplicate transaction/ledger rows.
3. Send a modified amount and an invalid signature; both must be rejected.
4. Run full and partial refunds, then provider reconciliation.
5. Confirm provider IDs and raw events are present in the finance audit response.

## E-signature

Set `SIGNATURE_PROVIDER=docusign` plus account, OAuth access token, return URL and webhook HMAC secret. Nestora creates the provider envelope, generates an embedded recipient view, verifies Connect HMAC, enforces local signing order and builds immutable evidence after all signers complete.

The access token must be rotated by the deployment secret manager. Do not store it in organization JSON or source control.

## Reconstruction and immersive viewing

`RECONSTRUCTION_BACKEND` accepts:

- `colmap`: real sparse/dense reconstruction and PLY output.
- `nerfstudio`: real `nerfacto` or `splatfacto` training/export.
- `fixture`: development/test only.

Use the `gpu` Compose profile:

```bash
docker compose --profile gpu build gpu-worker
docker compose --profile gpu up -d
```

The GPU image is based on the upstream Nerfstudio image and checks for `ns-process-data`, `ns-train`, `ns-export` and `colmap` during build. Captures are checksum-verified, subprocesses use argument arrays rather than a shell, execution is bounded by a timeout, and artifacts stay private until human approval.

Approved GLB/USDZ assets are exposed to:

- the React Three Fiber web viewer,
- Apple Quick Look,
- Android Scene Viewer,
- WebXR through the Three.js VR button.

## ML serving and rollback

An ML artifact may define:

```json
{
  "endpoint": "https://model.example/v1/predict",
  "health_url": "https://model.example/health",
  "authorization": "Bearer ...",
  "cost_per_request": 0.0002
}
```

Active deployments are selected with deterministic weighted routing from `traffic_percent`. Inference writes latency, cost, model and deployment IDs to `ml_usage_records`. Deployment health can automatically retire the unhealthy version and restore the previous deployment to 100% traffic.

Prefer injecting authorization through the model service/network layer or a secret reference rather than persisting a raw credential in artifact metadata.

## Mobile push and signed builds

- Device registration stores Expo push tokens.
- Organization-authorized users can send push notifications through `/api/v1/mobile/push`.
- Invalid `DeviceNotRegistered` tokens are disabled.
- Refresh rotation is atomic; reuse of a replaced token revokes the active token family for that device.
- `eas.json` defines development, preview and production AAB/IPA profiles.

Set `EAS_PROJECT_ID`, configure Expo/EAS credentials outside Git, then run:

```bash
npm run build:android --prefix apps/mobile
npm run build:ios --prefix apps/mobile
```

App Store/Play Store signing cannot be completed by source code alone; it requires the owner’s Apple/Google/Expo credentials.

## Database and security

- Migration `0003` uses frozen table/column assertions and Alembic operations instead of `Base.metadata.create_all`.
- Migration `0004` adds positive-amount/direction constraints, provider indexes and append-only ledger triggers.
- Production startup does not call `create_all`; deployment must run `alembic upgrade head` first.
- `security.yml` runs CodeQL, Bandit, pip-audit, npm audit, Gitleaks and Trivy.
