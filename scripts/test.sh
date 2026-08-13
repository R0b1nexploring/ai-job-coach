#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -x apps/api/.venv/bin/python ]] || { echo "缺少后端依赖，请先运行 ./scripts/dev.sh 或按 README 安装。"; exit 1; }
[[ -d apps/web/node_modules ]] || { echo "缺少前端依赖，请先在 apps/web 运行 npm install。"; exit 1; }

TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ai-job-coach-tests.XXXXXX")"
TEST_ROOT="$(cd "$TEST_ROOT" && pwd -P)"
cleanup() {
  if [[ -d "$TEST_ROOT" && "$(basename "$TEST_ROOT")" == ai-job-coach-tests.* ]]; then
    rm -rf -- "$TEST_ROOT"
  fi
}
trap cleanup EXIT
mkdir -p "$TEST_ROOT/uploads"

export AI_JOB_COACH_TEST_ROOT="$TEST_ROOT"
export APP_ENV=test
export DATABASE_URL="sqlite:///$TEST_ROOT/app.db"
export LOCAL_STORAGE_PATH="$TEST_ROOT/uploads"
export STORAGE_PROVIDER=local
export LLM_PROVIDER=mock
export LLM_API_BASE_URL=
export LLM_API_KEY=
export LLM_MODEL=
export LLM_MODEL_CHEAP=
export LLM_MODEL_STRONG=
export PAYMENT_PROVIDER=disabled
export JOB_SOURCE_ALLOWED_HOSTS=
export DEMO_ADMIN_EMAIL=admin@example.test
export DEMO_ADMIN_PASSWORD='ChangeMe123!'
export DEMO_ADVISOR_EMAIL=advisor@example.test
export DEMO_ADVISOR_PASSWORD='ChangeMe123!'
export DEMO_USER_EMAIL=user@example.test
export DEMO_USER_PASSWORD='ChangeMe123!'

(cd apps/api && .venv/bin/python -m pytest)
(cd apps/web && npm test -- --run)
(cd apps/web && npm run e2e)
