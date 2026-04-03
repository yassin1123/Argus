#!/usr/bin/env bash
# From repo root, after `docker compose up --build`:
#   bash tools/smoke_check.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== docker compose ps =="
docker compose ps

echo ""
echo "== Redis PING =="
docker compose exec -T redis redis-cli ping

echo ""
echo "== Backend /api/health =="
if curl -sf "http://localhost:8000/api/health" >/dev/null; then
  echo "OK"
else
  echo "FAIL (is the API up on port 8000?)"
  exit 1
fi

echo ""
echo "== Celery worker ping =="
if docker compose exec -T worker celery -A tasks.pipeline:celery_app inspect ping --timeout=5; then
  echo "OK"
else
  echo "FAIL — check: docker compose logs worker --tail 80"
  exit 1
fi

echo ""
echo "All checks passed."
