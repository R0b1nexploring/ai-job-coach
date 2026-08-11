import json
from time import perf_counter

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

from .base import ProviderError, log_call
from .json_repair import loads_lenient

MIN_OUTPUT_TOKENS = 256
MAX_OUTPUT_TOKENS = 8192


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
        format_instructions = _format_instructions(response_model)
        body = {
            "model": model,
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": max(
                MIN_OUTPUT_TOKENS,
                min(settings.llm_max_output_tokens, MAX_OUTPUT_TOKENS),
            ),
            "messages": [
                {
                    "role": "system",
                    "content": f"{system_prompt}\n\n{format_instructions}",
                },
                {"role": "user", "content": json.dumps(safe_payload, ensure_ascii=False)},
            ],
        }
        if settings.llm_thinking_enabled:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = settings.llm_reasoning_effort or "high"
        max_retries = max(0, settings.llm_max_retries)
        last_error_type = ""
        async with httpx.AsyncClient(
            timeout=settings.llm_timeout_seconds,
            transport=self.transport,
        ) as client:
            for attempt in range(max_retries + 1):
                try:
                    request_body = body
                    if attempt:
                        request_body = {
                            **body,
                            "messages": [
                                *body["messages"],
                                {
                                    "role": "system",
                                    "content": (
                                        "上一次响应未通过 JSON 解析或结构校验。请重新生成完整 JSON，"
                                        "严格使用规定字段和类型，不要输出解释、Markdown 或空对象。"
                                    ),
                                },
                            ],
                        }
                    response = await client.post(
                        settings.llm_api_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                        json=request_body,
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


def _format_instructions(response_model: type[BaseModel]) -> str:
    schema = response_model.model_json_schema()
    example = _schema_example(schema, schema)
    return (
        "必须只输出一个 JSON 对象，不要使用 Markdown 代码块。不得只返回空对象 {}。"
        "如果输入包含需要处理的事实、缺口或项目，不得静默返回空列表。"
        "以下示例只用于说明字段结构与类型，其中占位值不是事实，绝不能复制到正式结果。\n"
        f"JSON Schema：{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}\n"
        f"结构示例：{json.dumps(example, ensure_ascii=False, separators=(',', ':'))}"
    )


def _schema_example(node: dict, root: dict, depth: int = 0):
    if depth > 12:
        return None
    if ref := node.get("$ref"):
        target = root
        for part in ref.removeprefix("#/").split("/"):
            target = target[part]
        return _schema_example(target, root, depth + 1)
    if "const" in node:
        return node["const"]
    if values := node.get("enum"):
        return values[0]
    for alternatives_key in ("anyOf", "oneOf"):
        if alternatives := node.get(alternatives_key):
            selected = next(
                (item for item in alternatives if item.get("type") != "null"),
                alternatives[0],
            )
            return _schema_example(selected, root, depth + 1)
    value_type = node.get("type")
    if value_type == "object" or "properties" in node:
        return {
            name: _schema_example(value, root, depth + 1)
            for name, value in node.get("properties", {}).items()
        }
    if value_type == "array":
        if "必须为空数组" in str(node.get("description") or ""):
            return []
        return [_schema_example(node.get("items", {}), root, depth + 1)]
    if value_type == "integer":
        return 0
    if value_type == "number":
        return 0.0
    if value_type == "boolean":
        return False
    return "string"


def _token_count(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
