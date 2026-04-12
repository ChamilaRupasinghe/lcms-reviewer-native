#!/usr/bin/env bash
set -euo pipefail
BASE_DIR=/opt/lcms-reviewer/reviewer_app/prod_v4
cd "$BASE_DIR"

echo '== LCMS Reviewer v4 preflight =='
command -v docker >/dev/null || { echo 'docker not found'; exit 1; }
docker compose version >/dev/null || { echo 'docker compose not available'; exit 1; }
[ -f .env ] || { echo '.env missing'; exit 1; }
set -a
source .env
set +a

PORT=${SERVER_PORT:-4444}
if ss -ltn | awk '{print $4}' | grep -q ":${PORT}$"; then
  echo "port ${PORT} is already in use"
  exit 1
fi

FREE_KB=$(df -Pk /opt | awk 'NR==2 {print $4}')
if [ "$FREE_KB" -lt 5242880 ]; then
  echo 'less than 5 GB free on /opt'
  exit 1
fi

docker compose --env-file .env -f docker-compose.prod.yml config -q
echo 'preflight passed'
