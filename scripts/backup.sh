#!/usr/bin/env bash
set -euo pipefail
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S)
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-nestora}" -Fc "${POSTGRES_DB:-nestora}" > "backups/nestora-$stamp.dump"
echo "Created backups/nestora-$stamp.dump"
