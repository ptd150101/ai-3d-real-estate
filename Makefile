.PHONY: setup up down logs test migrate seed openapi backup restore
setup:
	@test -f .env || cp .env.example .env
up: setup
	docker compose up --build
down:
	docker compose down
logs:
	docker compose logs -f --tail=200
test:
	cd apps/api && pytest
migrate:
	docker compose run --rm migrate
openapi:
	cd apps/api && python ../../scripts/generate_openapi.py
backup:
	bash scripts/backup.sh
restore:
	bash scripts/restore.sh $(FILE)
