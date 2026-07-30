# System architecture

## Web

Next.js renders crawlable home, search, project, agent and property pages. Interactive search, MapLibre, chat and Three.js are isolated client components. The web app acts as a backend-for-frontend for authenticated calls: the browser receives an HTTP-only `nestora_token` cookie and `/api/backend/*` adds the bearer token server-side.

## API

FastAPI routers separate authentication, public listing search, engagement, chat/RAG, knowledge ingestion, uploads/jobs and administration. SQLAlchemy works with SQLite for tests and PostgreSQL in production. Alembic enables PostGIS and pgvector.

## Search

Relational filters use indexed columns. PostgreSQL radius search uses `ST_DWithin`; SQLite tests use Haversine fallback. Vietnamese natural-language parsing returns a validated filter object. Verified knowledge retrieval uses 256-dimensional deterministic embeddings and pgvector HNSW in PostgreSQL, with a JSON/cosine fallback for local tests.

## Chat

The deterministic tool router remains available without an external model, preventing the application from becoming unusable when an LLM provider is unavailable. An OpenAI-compatible client is included behind `ENABLE_LLM`. Sensitive facts are read from the database or verified knowledge chunks, not generated from memory. Mutating tools require a separate confirmed form.

## Media

Uploads are MIME- and size-validated. Local storage is available for development; MinIO/S3 is the Compose default. GLB uploads create a media-processing job. The included worker records validation/optimization recommendations and is the integration point for glTF Transform, DRACO/Meshopt and KTX2 tooling.

## Failure modes

- No LLM: deterministic tools continue to work.
- No Redis: in-process rate limiting/cache fallback.
- WebGL failure: poster and image gallery remain available.
- Model too large: background job reports budget/optimization requirements.
- Missing verified data: assistant explicitly says the information is unavailable and offers handoff.
