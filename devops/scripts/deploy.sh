#!/usr/bin/env bash
# Runs ON the EC2 server (called by the GitHub Action, or by hand).
# Rebuilds the image from the current checkout and restarts the container.
# The named volume holding the database and PDFs is NOT touched.
set -euo pipefail

cd "$(dirname "$0")/../.."

docker compose up -d --build --remove-orphans
bash devops/scripts/health_check.sh
docker image prune -f >/dev/null
echo "Deploy OK"