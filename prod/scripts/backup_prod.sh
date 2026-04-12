#!/usr/bin/env bash
set -euo pipefail
cd /opt/lcms-reviewer/reviewer_app/prod
source .env
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p backups

docker compose --env-file .env -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "backups/lcms_reviewer_${STAMP}.sql"

docker run --rm -v app_data:/data -v "$(pwd)/backups:/backups" alpine \
  sh -c "cd /data && tar -czf /backups/lcms_app_data_${STAMP}.tar.gz ."

echo "Backup written to $(pwd)/backups"
