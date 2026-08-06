# Nestora — AI + 3D Real Estate

A production-oriented real-estate marketplace for Vietnam with verified listing data, natural-language search, interactive Three.js property tours, contextual AI chat, mortgage calculations, lead/appointment workflows, and an administration console.

## What is implemented

- Next.js App Router public website, responsive desktop/mobile UI and SEO metadata.
- Search filters, Vietnamese natural-language query parsing, list/map views and pagination.
- Property detail, galleries, projects, agents, nearby places, favorites and 2–4 property comparison.
- Full-width React Three Fiber dollhouse viewer with orthographic/orbit/walk modes, auto-fit, floor isolation, floor explosion, roof and furniture toggles, room hotspots, quality scaling and fullscreen.
- Deterministic local demo catalog with 72 listings, 24 interactive 3D listings, 8 generated GLB templates, 12 agents, 4 agencies and 6 projects.
- Contextual chatbot with SSE streaming and deterministic tools for property facts, search, comparison, nearby places, mortgage, appointments, lead capture and human handoff.
- Verified-document RAG with deterministic embeddings for SQLite and pgvector/HNSW retrieval on PostgreSQL.
- FastAPI, SQLAlchemy, Alembic, PostgreSQL/PostGIS, Redis cache adapter, MinIO/S3 storage and a background media worker.
- Authentication with HTTP-only web cookie, API bearer tokens, PBKDF2 password hashing and role-based access control.
- Admin property CRUD, media/GLB upload, floor/hotspot JSON editing, publish workflow, appointments, leads, knowledge documents and audit logs.
- Backend tests, Playwright smoke tests, Docker Compose, CI, backups and operational documentation.

## Full Docker stack

```bash
cp .env.example .env
# Set SECRET_KEY, POSTGRES_PASSWORD, S3_ACCESS_KEY and S3_SECRET_KEY.
# Keep DATABASE_URL's password equal to POSTGRES_PASSWORD.
docker compose up --build
```

Open:

- Web: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`

## Hybrid development

You can run only PostgreSQL, Redis and MinIO in Docker, then run the API, worker and web manually for hot reload.

```bash
cp .env.example .env
docker compose up -d postgres redis minio minio-init
```

Run the API from a second terminal. `uv run` creates or updates `apps/api/.venv` and installs the dependencies declared in `pyproject.toml` automatically.

```bash
cd apps/api
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run the background worker from a third terminal:

```bash
cd apps/api
uv run --env-file ../../.env python -m app.worker
```

Run the frontend from another terminal:

```bash
npm install --prefix apps/web
npm --prefix apps/web run dev
```

Cross-platform helpers accept one of `infra`, `api`, `worker` or `web`:

```powershell
.\scripts\dev.ps1 infra
.\scripts\dev.ps1 api
```

```bash
bash scripts/dev.sh infra
bash scripts/dev.sh api
```

```bat
scripts\dev.bat infra
scripts\dev.bat api
```

## Deterministic demo dataset

The API startup performs an idempotent upsert. You can also run the seed explicitly:

```bash
make seed-demo
# or
cd apps/api
uv run --env-file ../../.env python -m app.cli.seed_demo --preset mvp --upsert
```

Reset only records owned by the demo catalog and rebuild all generated assets:

```bash
make reset-demo
```

The `mvp` preset contains:

- 72 published properties across 11 Hà Nội districts.
- 48 sale and 24 rental listings.
- 24 properties with interactive 3D.
- 8 deterministic GLB dollhouse templates generated locally.
- 4 agencies, 12 agents and 6 projects.
- Five local SVG gallery images, 5–9 amenities, four nearby places and one knowledge document per listing.

Fixture reconstruction accepts a minimum of one capture in non-production environments, emits real GLB content, advances through the normal review workflow and synchronizes an approved artifact into `PropertyModel3D`.

## Local checks

```bash
cd apps/api
uv run python -m compileall -q app alembic
uv run pytest --cov=app --cov-report=term-missing
uv run python ../../scripts/generate_openapi.py
npm install --prefix ../../apps/web
npm --prefix ../../apps/web run typecheck
npm --prefix ../../apps/web run build
```

Seed users are documented in `docs/DEPLOYMENT.md`. Replace every local development credential and `SECRET_KEY` before exposing the system publicly.

Production assets should still be optimized with glTF Transform or an equivalent media pipeline before publishing.

## Architecture

```text
Browser
  └─ Next.js Web/BFF
      ├─ SSR/SEO pages
      ├─ MapLibre search
      ├─ React Three Fiber dollhouse viewer
      └─ HTTP-only auth proxy
           └─ FastAPI
               ├─ PostgreSQL + PostGIS + pgvector
               ├─ Redis cache/rate-limit adapter
               ├─ MinIO/S3 media
               ├─ background worker
               └─ optional OpenAI-compatible LLM
```

See [`docs/`](docs/) for the product brief, architecture, data model, security model, deployment runbook and acceptance checklist.
