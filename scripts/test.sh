#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -x apps/api/.venv/bin/python ]] || { echo "缺少后端依赖，请先运行 ./scripts/dev.sh 或按 README 安装。"; exit 1; }
[[ -d apps/web/node_modules ]] || { echo "缺少前端依赖，请先在 apps/web 运行 npm install。"; exit 1; }
(cd apps/api && .venv/bin/python -m pytest)
(cd apps/web && npm test -- --run)
(cd apps/web && npm run e2e)
