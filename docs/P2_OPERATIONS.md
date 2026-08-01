# P2 operations runbook

## Feature control

Every high-risk P2 capability is organization-scoped. Disable a capability using its organization feature flag or the platform `feature_kill_switches` record. Payment, contract, valuation, recommendation, reconstruction, AR, VR, mobile and ML Ops can be disabled without redeployment.

## Worker separation

The normal `worker` service starts with `WORKER_CAPABILITIES=cpu` and cannot claim `p2.reconstruction`. The `gpu-worker` service belongs to the Compose `gpu` profile and starts with `WORKER_CAPABILITIES=cpu,gpu`.

```bash
# Standard application
docker compose up -d --build

# Include reconstruction worker
docker compose --profile gpu up -d --build
```

Production GPU images should install pinned COLMAP/Nerfstudio versions and expose the same durable-job contract. The CI image intentionally uses the deterministic fixture implementation.

## Payment incident

1. Enable the `payments` kill switch for affected organizations.
2. Preserve webhook payloads and provider event IDs; never replay by editing ledger rows.
3. Run the reconciliation endpoint as a finance user.
4. Resolve exceptions through compensating payment/refund transactions.
5. Verify each transaction remains balanced before re-enabling checkout.

## Contract incident

1. Disable the `contracts` flag.
2. Preserve original PDF, checksum, signer timeline and provider evidence.
3. Void the envelope rather than replacing signed bytes.
4. Require a new template version for corrected content.

## AI incident

Valuation drift can disable display through the model gate. Roll back the ML deployment and retain the original feature snapshot and prediction. Recommendation failures fall back to deterministic search.

## Backup and restore

Use `scripts/backup.sh` and `scripts/restore.sh`. Production backups must include PostgreSQL plus the private object bucket. CI performs a PostgreSQL dump/restore rehearsal; object-storage recovery must be tested in staging with the configured provider.
