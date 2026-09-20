#!/usr/bin/env bash
# Daily backup of PostgreSQL and the private MinIO bucket.
# Schedule from cron/systemd-timer, e.g.:
#   15 3 * * * /srv/ai-job-coach/scripts/backup.sh >> /var/log/aijc-backup.log 2>&1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.prod.yml"
ENV_FILE="$ROOT/.env"

[[ -f "$ENV_FILE" ]] || { echo "缺少 $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

BACKUP_DIR="${BACKUP_DIR:-$ROOT/var/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/$STAMP"
PROJECT="${COMPOSE_PROJECT_NAME:-ai-job-coach}"

mkdir -p "$DEST"
chmod 700 "$BACKUP_DIR" "$DEST"

echo "[backup] postgres -> $DEST/postgres.sql.gz"
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip -9 > "$DEST/postgres.sql.gz"

echo "[backup] minio bucket '$S3_BUCKET' -> $DEST/minio"
docker run --rm \
  --network "${PROJECT}_default" \
  -v "$DEST/minio:/backup" \
  -e S3_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" \
  -e S3_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
  -e S3_BUCKET="$S3_BUCKET" \
  minio/mc:latest \
  /bin/sh -c '
    mc alias set local http://minio:9000 "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY" >/dev/null
    mc mirror --overwrite --remove "local/$S3_BUCKET" /backup
  '

# Optional client-side encryption at rest.
if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]] && command -v age >/dev/null 2>&1; then
  echo "[backup] encrypting with age"
  tar -C "$DEST" -cf - . | age -r "$BACKUP_AGE_RECIPIENT" > "$DEST.tar.age"
  rm -rf "$DEST"
  echo "[backup] wrote $DEST.tar.age"
else
  echo "[backup] wrote $DEST (unencrypted; store on an encrypted volume)"
fi

echo "[backup] pruning entries older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -mtime "+$RETENTION_DAYS" -exec rm -rf {} +

echo "[backup] done"
