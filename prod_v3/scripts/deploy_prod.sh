#!/usr/bin/env bash
set -euo pipefail
TARGET=/opt/lcms-reviewer
mkdir -p "$TARGET"
rsync -av --delete ./ "$TARGET/"
cd "$TARGET/reviewer_app/prod_v3"
if [ ! -f .env ]; then
  cp .env.example .env
  echo 'Created .env from .env.example. Edit secrets before starting.'
fi
./scripts/preflight_check.sh
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
docker compose --env-file .env -f docker-compose.prod.yml ps
echo 'Open http://10.117.1.148:4444/'
