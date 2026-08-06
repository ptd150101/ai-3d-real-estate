#!/usr/bin/env bash
set -euo pipefail

command_name=${1:-infra}
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
env_file="$root/.env"

if [[ ! -f "$env_file" ]]; then
  cp "$root/.env.example" "$env_file"
  echo "Created .env from .env.example. Set the required local credentials before continuing."
fi

case "$command_name" in
  infra)
    cd "$root"
    docker compose up -d postgres redis minio minio-init
    ;;
  api)
    cd "$root/apps/api"
    uv run --env-file "$env_file" alembic upgrade head
    exec uv run --env-file "$env_file" uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ;;
  worker)
    cd "$root/apps/api"
    exec uv run --env-file "$env_file" python -m app.worker
    ;;
  web)
    cd "$root"
    npm install --prefix apps/web
    exec npm --prefix apps/web run dev
    ;;
  *)
    echo "Usage: scripts/dev.sh {infra|api|worker|web}" >&2
    exit 2
    ;;
esac
