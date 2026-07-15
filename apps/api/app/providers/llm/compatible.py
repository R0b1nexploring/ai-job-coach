import json

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from .base import ProviderError


class CompatibleLLMProvider:
    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[BaseModel]
    ):
        settings = get_settings()
        if not all([settings.llm_api_base_url, settings.llm_api_key, settings.llm_model]):
            raise ProviderError("真实 LLM Provider 配置不完整")
        safe_payload = {key: value for key, value in user_payload.items() if key != "mock_response"}
        body = {
            "model": settings.llm_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(safe_payload, ensure_ascii=False)},
            ],
        }
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        settings.llm_api_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                        json=body,
                    )
                    response.raise_for_status()
                    raw = response.json()["choices"][0]["message"]["content"]
                    return response_model.model_validate_json(raw)
                except (httpx.HTTPError, KeyError, ValidationError, ValueError) as exc:
                    if attempt == 1:
                        raise ProviderError("LLM Provider 返回无效结构化结果") from exc
