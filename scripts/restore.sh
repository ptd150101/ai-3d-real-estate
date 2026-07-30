#!/usr/bin/env bash
set -euo pipefail
file=${1:-}
if [[ -z "$file" || ! -f "$file" ]]; then echo "Usage: scripts/restore.sh backups/file.dump"; exit 1; fi
docker compose exec -T postgres pg_restore -U "${POSTGRES_USER:-nestora}" -d "${POSTGRES_DB:-nestora}" --clean --if-exists < "$file"
