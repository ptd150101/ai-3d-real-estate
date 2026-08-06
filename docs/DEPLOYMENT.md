# Deployment runbook

## Environments

Use separate PostgreSQL, Redis, object-storage buckets and secrets for development, staging and production. Never share seed credentials.

For a local seed, set all three password environment variables before first boot:

- `SEED_ADMIN_PASSWORD` for `admin@nestora.vn`
- `SEED_AGENT_PASSWORD` for `agent@nestora.vn`
- `SEED_BUYER_PASSWORD` for `buyer@nestora.vn`

When those variables are absent, random one-time passwords are generated and are not printed or persisted. Production should create accounts through an approved identity workflow instead of relying on seed users.

## Python environment

The API is a uv project in `apps/api/pyproject.toml` and requires Python `>=3.13,<3.14`. Use `uv sync` to prepare the environment and `uv run` for every Python command. `uv run` also creates or updates the project environment automatically when needed.

## Release

1. Build immutable API and web images.
2. Run `uv run alembic upgrade head` as a one-shot migration job inside the API image or its equivalent deployment job.
3. Deploy API and worker, verify `/ready`.
4. Deploy web and run smoke tests.
5. Observe error rate, p95 latency, DB connections and viewer failures.

## Hybrid local development

Start only the supporting services:

```bash
docker compose up -d postgres redis minio minio-init
```

Then run the API and worker manually from `apps/api` with the root `.env` file:

```bash
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
uv run --env-file ../../.env python -m app.worker
```

## Backup and restore

`scripts/backup.sh` creates a custom-format PostgreSQL dump. Test `scripts/restore.sh` against a disposable database regularly. Object storage requires independent versioning/replication.

## Rollback

Application images can be rolled back independently when migrations are backward compatible. Destructive migrations must use expand/migrate/contract phases.
