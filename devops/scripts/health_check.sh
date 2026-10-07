#!/usr/bin/env bash
# Waits until GET /health answers, otherwise prints recent logs and fails.
# Usage: health_check.sh [url]   (default http://localhost:8000/health)
set -uo pipefail

URL="${1:-http://localhost:8000/health}"

for attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 "$URL" >/dev/null 2>&1; then
    echo "Healthy: $URL (attempt $attempt)"
    exit 0
  fi
  sleep 2
done

echo "NOT healthy after 60s: $URL" >&2
docker compose logs --tail=50 >&2 || true
exit 1