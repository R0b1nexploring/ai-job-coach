#!/usr/bin/env bash
# Restore PostgreSQL and the MinIO bucket from a backup produced by backup.sh.
#
#   scripts/restore.sh /srv/ai-job-coach/var/backups/20260101T030000Z
#
# Stop writers first: `docker compose -f docker-compose.prod.yml stop api worker`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.prod.yml"
ENV_FILE="$ROOT/.env"

[[ $# -eq 1 ]] || { echo "用法: $0 <备份目录>" >&2; exit 1; }
SOURCE="$1"
[[ -d "$SOURCE" ]] || { echo "备份目录不存在: $SOURCE" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "缺少 $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a
PROJECT="${COMPOSE_PROJECT_NAME:-ai-job-coach}"

read -r -p "将覆盖数据库 '$POSTGRES_DB' 和存储桶 '$S3_BUCKET'，确认？[y/N] " answer
[[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "已取消"; exit 1; }

echo "[restore] postgres <- $SOURCE/postgres.sql.gz"
gunzip -c "$SOURCE/postgres.sql.gz" | docker compose -f "$COMPOSE_FILE" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"

echo "[restore] minio <- $SOURCE/minio"
docker run --rm \
  --network "${PROJECT}_default" \
  -v "$SOURCE/minio:/backup:ro" \
  -e S3_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" \
  -e S3_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
  -e S3_BUCKET="$S3_BUCKET" \
  minio/mc:latest \
  /bin/sh -c '
    mc alias set local http://minio:9000 "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY" >/dev/null
    mc mirror --overwrite --remove /backup "local/$S3_BUCKET"
  '

echo "[restore] 完成。启动服务：docker compose -f docker-compose.prod.yml start api worker"
