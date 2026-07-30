#!/usr/bin/env bash
set -euo pipefail
curl -fsS http://localhost:8000/health
curl -fsS 'http://localhost:8000/api/v1/properties?page_size=1'
curl -fsS http://localhost:3000 >/dev/null
echo "Smoke checks passed"
