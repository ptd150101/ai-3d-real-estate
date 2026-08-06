.PHONY: setup up infra down logs test migrate migrate-docker dev-api dev-worker dev-web openapi backup restore

setup:
	@test -f .env || cp .env.example .env

up: setup
	docker compose up --build

infra: setup
	docker compose up -d postgres redis minio minio-init

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

test:
	cd apps/api && uv run pytest

migrate: setup
	cd apps/api && uv run --env-file ../../.env alembic upgrade head

migrate-docker: setup
	docker compose run --rm migrate

dev-api: setup
	cd apps/api && uv run --env-file ../../.env alembic upgrade head
	cd apps/api && uv run --env-file ../../.env uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-worker: setup
	cd apps/api && uv run --env-file ../../.env python -m app.worker

dev-web:
	npm install --prefix apps/web
	npm --prefix apps/web run dev

openapi:
	cd apps/api && uv run python ../../scripts/generate_openapi.py

backup:
	bash scripts/backup.sh

restore:
	bash scripts/restore.sh $(FILE)
