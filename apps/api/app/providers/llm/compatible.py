import json
from time import perf_counter

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings

from .base import ProviderError, log_call
from .json_repair import loads_lenient

MIN_OUTPUT_TOKENS = 256
MAX_OUTPUT_TOKENS = 8192
TRANSIENT_STATUS_CODES = {408, 425, 429}


class _CompletionMessage(BaseModel):
    content: str = Field(min_length=1)


class _CompletionChoice(BaseModel):
    message: _CompletionMessage


class _CompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _CompletionEnvelope(BaseModel):
    choices: list[_CompletionChoice] = Field(min_length=1)
    usage: _CompletionUsage = Field(default_factory=_CompletionUsage)


class CompatibleLLMProvider:
    def __init__(self, *, transport=None):
        self.transport = transport

    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[BaseModel]
    ):
        settings = get_settings()
        api_key = settings.llm_api_key.get_secret_value()
        tier = settings.tier_for(task)
        model = settings.model_for(task)
        started_at = perf_counter()
        if not all([settings.llm_api_base_url, api_key, model]):
            log_call(
                task=task,
                tier=tier,
                model=model or "unconfigured",
                duration_ms=int((perf_counter() - started_at) * 1000),
                error_type="ConfigurationError",
            )
            raise ProviderError(
                "真实 LLM Provider 配置不完整",
                code="LLM_CONFIGURATION_ERROR",
            )
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
            follow_redirects=False,
        ) as client:
            for attempt in range(max_retries + 1):
                provider_error: ProviderError | None = None
                cause: Exception | None = None
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
                                        "上一次响应未通过 JSON 解析或结构校验。"
                                        "请重新生成完整 JSON，"
                                        "严格使用规定字段和类型，不要输出解释、Markdown 或空对象。"
                                    ),
                                },
                            ],
                        }
                    response = await client.post(
                        settings.llm_api_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json=request_body,
                    )
                    response.raise_for_status()
                    envelope = _CompletionEnvelope.model_validate(response.json())
                    raw = envelope.choices[0].message.content
                    result = response_model.model_validate(loads_lenient(raw))
                    log_call(
                        task=task,
                        tier=tier,
                        model=model,
                        duration_ms=int((perf_counter() - started_at) * 1000),
                        prompt_tokens=_token_count(envelope.usage.prompt_tokens),
                        completion_tokens=_token_count(envelope.usage.completion_tokens),
                        retried=attempt > 0,
                        error_type=last_error_type,
                    )
                    return result
                except httpx.HTTPStatusError as exc:
                    last_error_type = type(exc).__name__
                    status_code = exc.response.status_code
                    provider_error = ProviderError(
                        "LLM Provider 请求失败",
                        code="LLM_UPSTREAM_HTTP_ERROR",
                        retryable=status_code in TRANSIENT_STATUS_CODES or status_code >= 500,
                    )
                    cause = exc
                except (httpx.DecodingError, httpx.UnsupportedProtocol) as exc:
                    # A broken content encoding or unsupported URL cannot be
                    # repaired by repeating the paid request unchanged.
                    last_error_type = type(exc).__name__
                    provider_error = ProviderError(
                        "LLM Provider 配置或响应编码无效",
                        code="LLM_UPSTREAM_INVALID_RESPONSE",
                        retryable=False,
                    )
                    cause = exc
                except httpx.RequestError as exc:
                    # Covers timeouts and connection/proxy/protocol failures.
                    # Keep the public error deliberately generic: exception
                    # text can contain a request URL or proxy credentials.
                    last_error_type = type(exc).__name__
                    provider_error = ProviderError(
                        "LLM Provider 暂时不可达",
                        code="LLM_UPSTREAM_UNAVAILABLE",
                        retryable=True,
                    )
                    cause = exc
                except (ValidationError, TypeError, ValueError) as exc:
                    # A syntactically successful response with the wrong shape
                    # is not a transient transport failure. Retrying it hides a
                    # broken provider contract and can multiply paid calls.
                    last_error_type = type(exc).__name__
                    provider_error = ProviderError(
                        "LLM Provider 返回无效结构化结果",
                        code="LLM_MALFORMED_RESPONSE",
                        retryable=False,
                    )
                    cause = exc

                if provider_error.retryable and attempt < max_retries:
                    continue
                log_call(
                    task=task,
                    tier=tier,
                    model=model,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    retried=attempt > 0,
                    error_type=last_error_type,
                )
                raise provider_error from cause


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
