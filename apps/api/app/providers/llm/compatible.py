import json
from time import perf_counter

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

from .base import ProviderError, log_call
from .json_repair import loads_lenient


class CompatibleLLMProvider:
    def __init__(self, *, transport=None):
        self.transport = transport

    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[BaseModel]
    ):
        settings = get_settings()
        tier = settings.tier_for(task)
        model = settings.model_for(task)
        started_at = perf_counter()
        if not all([settings.llm_api_base_url, settings.llm_api_key, model]):
            log_call(
                task=task,
                tier=tier,
                model=model or "unconfigured",
                duration_ms=int((perf_counter() - started_at) * 1000),
                error_type="ConfigurationError",
            )
            raise ProviderError("真实 LLM Provider 配置不完整")
        safe_payload = {key: value for key, value in user_payload.items() if key != "mock_response"}
        body = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(safe_payload, ensure_ascii=False)},
            ],
        }
        max_retries = max(0, settings.llm_max_retries)
        last_error_type = ""
        async with httpx.AsyncClient(
            timeout=settings.llm_timeout_seconds,
            transport=self.transport,
        ) as client:
            for attempt in range(max_retries + 1):
                try:
                    response = await client.post(
                        settings.llm_api_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                        json=body,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    raw = payload["choices"][0]["message"]["content"]
                    result = response_model.model_validate(loads_lenient(raw))
                    usage = payload.get("usage") if isinstance(payload, dict) else None
                    usage = usage if isinstance(usage, dict) else {}
                    log_call(
                        task=task,
                        tier=tier,
                        model=model,
                        duration_ms=int((perf_counter() - started_at) * 1000),
                        prompt_tokens=_token_count(usage.get("prompt_tokens")),
                        completion_tokens=_token_count(usage.get("completion_tokens")),
                        retried=attempt > 0,
                        error_type=last_error_type,
                    )
                    return result
                except (
                    httpx.HTTPError,
                    AttributeError,
                    KeyError,
                    TypeError,
                    ValidationError,
                    ValueError,
                ) as exc:
                    last_error_type = type(exc).__name__
                    if attempt == max_retries:
                        log_call(
                            task=task,
                            tier=tier,
                            model=model,
                            duration_ms=int((perf_counter() - started_at) * 1000),
                            retried=attempt > 0,
                            error_type=last_error_type,
                        )
                        raise ProviderError("LLM Provider 返回无效结构化结果") from exc


def _token_count(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
