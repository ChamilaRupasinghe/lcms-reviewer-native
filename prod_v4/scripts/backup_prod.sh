#!/usr/bin/env bash
set -euo pipefail
BASE_DIR=/opt/lcms-reviewer/reviewer_app/prod_v4
cd "$BASE_DIR"
set -a
source .env
set +a
STAMP=$(date +%Y%m%d_%H%M%S)
RETENTION=${BACKUP_RETENTION_DAYS:-14}
BACKUP_DIR=${BACKUP_DIR:-/opt/lcms-reviewer/backups}
mkdir -p "$BACKUP_DIR"

DB_FILE="$BACKUP_DIR/lcms_reviewer_db_${STAMP}.sql.gz"
APP_FILE="$BACKUP_DIR/lcms_reviewer_app_data_${STAMP}.tar.gz"
MANIFEST="$BACKUP_DIR/lcms_reviewer_manifest_${STAMP}.txt"

docker compose --env-file .env -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip -9 > "$DB_FILE"

docker run --rm -v ${COMPOSE_PROJECT_NAME}_app_data:/data -v "$BACKUP_DIR:/backups" alpine \
  sh -c "cd /data && tar -czf /backups/$(basename "$APP_FILE") ."

{
  echo "timestamp=$STAMP"
  echo "db_backup=$(basename "$DB_FILE")"
  echo "app_backup=$(basename "$APP_FILE")"
  echo "compose_project=${COMPOSE_PROJECT_NAME}"
} > "$MANIFEST"

find "$BACKUP_DIR" -type f -mtime +"$RETENTION" -delete

echo "Backup completed in $BACKUP_DIR"
