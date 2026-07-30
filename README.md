# Nestora — AI + 3D Real Estate

A production-oriented real-estate marketplace for Vietnam with verified listing data, natural-language search, interactive Three.js property tours, contextual AI chat, mortgage calculations, lead/appointment workflows, and an administration console.

## What is implemented

- Next.js App Router public website, responsive desktop/mobile UI and SEO metadata.
- Search filters, Vietnamese natural-language query parsing, list/map views and pagination.
- Property detail, galleries, projects, agents, nearby places, favorites and 2–4 property comparison.
- GLB viewer using React Three Fiber: lazy loading, orbit, floor visibility, furniture toggle, hotspots, quality scaling, fullscreen, reset and walk mode.
- Contextual chatbot with SSE streaming and deterministic tools for property facts, search, comparison, nearby places, mortgage, appointments, lead capture and human handoff.
- Verified-document RAG with deterministic embeddings for SQLite and pgvector/HNSW retrieval on PostgreSQL.
- FastAPI, SQLAlchemy, Alembic, PostgreSQL/PostGIS, Redis cache adapter, MinIO/S3 storage and a background media worker.
- Authentication with HTTP-only web cookie, API bearer tokens, PBKDF2 password hashing and role-based access control.
- Admin property CRUD, media/GLB upload, floor/hotspot JSON editing, publish workflow, appointments, leads, knowledge documents and audit logs.
- Backend tests, Playwright smoke tests, Docker Compose, CI, backups and operational documentation.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Web: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`

Seed users are documented in `docs/DEPLOYMENT.md`. Replace every local development credential and `SECRET_KEY` before exposing the system publicly.

## Local checks

```bash
cd apps/api && pytest
python scripts/generate_openapi.py
npm install
npm --workspace apps/web run typecheck
npm --workspace apps/web run build
```

The repository includes a compact sample GLB at `apps/web/public/models/demo-house.glb`. Production assets should be optimized with glTF Transform or an equivalent media pipeline before publishing.

## Architecture

```text
Browser
  └─ Next.js Web/BFF
      ├─ SSR/SEO pages
      ├─ MapLibre search
      ├─ React Three Fiber viewer
      └─ HTTP-only auth proxy
           └─ FastAPI
               ├─ PostgreSQL + PostGIS + pgvector
               ├─ Redis cache/rate-limit adapter
               ├─ MinIO/S3 media
               ├─ background worker
               └─ optional OpenAI-compatible LLM
```

See [`docs/`](docs/) for the product brief, architecture, data model, security model, deployment runbook and acceptance checklist.
