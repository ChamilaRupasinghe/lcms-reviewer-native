#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo 'Usage: restore_prod.sh /path/to/db.sql.gz /path/to/app_data.tar.gz'
  exit 1
fi
DB_BACKUP=$1
APP_BACKUP=$2
BASE_DIR=/opt/lcms-reviewer/reviewer_app/prod_v4
cd "$BASE_DIR"
set -a
source .env
set +a

docker compose --env-file .env -f docker-compose.prod.yml down

docker compose --env-file .env -f docker-compose.prod.yml up -d db
sleep 10

gunzip -c "$DB_BACKUP" | docker compose --env-file .env -f docker-compose.prod.yml exec -T db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

docker run --rm -v ${COMPOSE_PROJECT_NAME}_app_data:/data -v "$(dirname "$APP_BACKUP"):/backups" alpine \
  sh -c "rm -rf /data/* && cd /data && tar -xzf /backups/$(basename "$APP_BACKUP")"

docker compose --env-file .env -f docker-compose.prod.yml up -d --build

echo 'Restore completed'
