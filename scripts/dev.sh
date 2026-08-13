#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_API_BIND="${DEV_API_HOST:-127.0.0.1}"
DEV_WEB_BIND="${DEV_WEB_HOST:-127.0.0.1}"
cd "$ROOT"
if [[ "$ROOT" == /mnt/c/* ]]; then
  echo "错误：当前位于 /mnt/c。请将仓库移到 ~/projects 后再安装 WSL 依赖。" >&2
  exit 1
fi
[[ -f .env ]] || cp .env.example .env
chmod 600 .env
mkdir -p var/uploads
chmod 700 var var/uploads
python3 -m venv apps/api/.venv
apps/api/.venv/bin/python -m pip install -e 'apps/api[dev]'
(cd apps/api && .venv/bin/python -m alembic upgrade head)
[[ -f var/app.db ]] && chmod 600 var/app.db
apps/api/.venv/bin/python scripts/seed_demo.py
(cd apps/api && .venv/bin/python -m uvicorn app.main:app --reload --host "$DEV_API_BIND" --port 8000) &
API_PID=$!
(cd apps/web && npm install && npm run dev -- --host "$DEV_WEB_BIND") &
WEB_PID=$!
trap 'kill "$API_PID" "$WEB_PID" 2>/dev/null || true' EXIT INT TERM
wait
