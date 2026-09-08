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

# Keep the API port in one place. API_BASE_URL is not read by the local Vite
# proxy; API_PORT is passed to both processes below.
ENV_API_PORT=""
if [[ -f .env ]]; then
  ENV_API_PORT="$(awk -F= '$1 == "API_PORT" {print $2; exit}' .env | tr -d '\r' | xargs)"
fi
DEV_API_PORT="${API_PORT:-${ENV_API_PORT:-8000}}"
if ! [[ "$DEV_API_PORT" =~ ^[0-9]+$ ]] || (( DEV_API_PORT < 1 || DEV_API_PORT > 65535 )); then
  echo "错误：API_PORT 必须是 1-65535 的端口号，当前为 '$DEV_API_PORT'。" >&2
  exit 1
fi
DEV_WILDCARD_BIND="$(printf '%s.%s.%s.%s' 0 0 0 0)"
case "$DEV_API_BIND" in
  "$DEV_WILDCARD_BIND"|::|::0) DEV_API_CHECK_HOST="127.0.0.1" ;;
  *) DEV_API_CHECK_HOST="$DEV_API_BIND" ;;
esac
if [[ "$DEV_API_CHECK_HOST" == *:* ]]; then
  DEV_API_CHECK_URL_HOST="[$DEV_API_CHECK_HOST]"
else
  DEV_API_CHECK_URL_HOST="$DEV_API_CHECK_HOST"
fi

# Fail before starting the web server when another process owns the API port.
# Otherwise uvicorn can exit in the background while Vite keeps running.
if ! python3 - "$DEV_API_BIND" "$DEV_API_PORT" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
for family, socktype, protocol, _, address in socket.getaddrinfo(
    host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
):
    sock = socket.socket(family, socktype, protocol)
    try:
        sock.bind(address)
    except OSError:
        sock.close()
        continue
    sock.close()
    raise SystemExit(0)
raise SystemExit(1)
PY
then
  echo "错误：API 端口 $DEV_API_PORT 已被占用。请停止占用进程，或使用 API_PORT=其他端口 ./scripts/dev.sh。" >&2
  exit 1
fi

API_PID=""
WORKER_PID=""
WEB_PID=""
cleanup() {
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$WORKER_PID" ]] && kill "$WORKER_PID" 2>/dev/null || true
  [[ -n "$WEB_PID" ]] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python3 -m venv apps/api/.venv
apps/api/.venv/bin/python -m pip install -e 'apps/api[dev]'
(cd apps/api && .venv/bin/python -m alembic upgrade head)
[[ -f var/app.db ]] && chmod 600 var/app.db
apps/api/.venv/bin/python scripts/seed_demo.py
(cd apps/api && .venv/bin/python -m app.worker) &
WORKER_PID=$!
(cd apps/api && .venv/bin/python -m uvicorn app.main:app --reload --host "$DEV_API_BIND" --port "$DEV_API_PORT") &
API_PID=$!

# Do not start the web server until this exact process serves /api/health.
API_READY=false
for _attempt in {1..30}; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "错误：API 进程启动失败，请检查上面的 uvicorn 日志。" >&2
    exit 1
  fi
  if curl -fsS --max-time 2 "http://${DEV_API_CHECK_URL_HOST}:${DEV_API_PORT}/api/health" \
    | python3 -c 'import json, sys; raise SystemExit(0 if json.load(sys.stdin).get("status") == "ok" else 1)' \
    >/dev/null 2>&1; then
    API_READY=true
    break
  fi
  sleep 1
done
if [[ "$API_READY" != true ]]; then
  echo "错误：API 在 30 秒内未就绪，请访问 http://127.0.0.1:${DEV_API_PORT}/api/health 检查。" >&2
  exit 1
fi

# Vite reads API_PORT from its process environment, so its proxy always follows
# the selected uvicorn port.
(cd apps/web && E2E_API_PORT="" API_PORT="$DEV_API_PORT" npm install && E2E_API_PORT="" API_PORT="$DEV_API_PORT" npm run dev -- --host "$DEV_WEB_BIND") &
WEB_PID=$!
wait
