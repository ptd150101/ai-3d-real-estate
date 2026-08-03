#!/usr/bin/env bash
set -euo pipefail
base=${BASE_URL:-http://localhost:8000}
parallelism=${PARALLELISM:-8}
requests=${REQUESTS:-40}
seq "$requests" | xargs -P "$parallelism" -I{} sh -c "curl -fsS '$base/api/v1/properties?page_size=3' >/dev/null"
echo "P2 load smoke passed: $requests requests, concurrency $parallelism"
