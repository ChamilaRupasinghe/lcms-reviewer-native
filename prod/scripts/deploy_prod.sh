#!/usr/bin/env bash
set -euo pipefail
APP_ROOT=/opt/lcms-reviewer
mkdir -p "$APP_ROOT"
rsync -av --delete ./ "$APP_ROOT/"
cd "$APP_ROOT/reviewer_app/prod"
if [ ! -f .env ]; then
  cp .env.example .env
  echo 'Created .env from .env.example. Edit credentials before first start.'
fi
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
echo 'LCMS Reviewer should be reachable at http://SERVER_IP:4444/'
