#!/bin/bash
set -euo pipefail

: "${LLM_PROVIDER:=mock}"
export LLM_PROVIDER

if [[ "$LLM_PROVIDER" == "compatible" ]]; then
  : "${LLM_API_BASE_URL:?使用 compatible Provider 时必须设置 LLM_API_BASE_URL}"
  : "${LLM_API_KEY:?使用 compatible Provider 时必须设置 LLM_API_KEY}"
  : "${LLM_MODEL:?使用 compatible Provider 时必须设置 LLM_MODEL}"
fi

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
