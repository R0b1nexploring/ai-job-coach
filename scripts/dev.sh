#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "$ROOT" == /mnt/c/* ]]; then
  echo "错误：当前位于 /mnt/c。请将仓库移到 ~/projects 后再安装 WSL 依赖。" >&2
  exit 1
fi
[[ -f .env ]] || cp .env.example .env
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -e 'apps/api[dev]'
(cd apps/api && .venv/bin/alembic upgrade head)
apps/api/.venv/bin/python scripts/seed_demo.py
(cd apps/api && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
API_PID=$!
(cd apps/web && npm install && npm run dev -- --host 0.0.0.0) &
WEB_PID=$!
trap 'kill "$API_PID" "$WEB_PID" 2>/dev/null || true' EXIT INT TERM
wait

