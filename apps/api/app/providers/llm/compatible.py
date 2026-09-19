import asyncio
import email.utils
import json
import random
from datetime import UTC, datetime
from time import perf_counter

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings

from .base import ProviderError, log_call
from .json_repair import loads_lenient

MIN_OUTPUT_TOKENS = 256
# Reasoning models spend part of the completion budget on hidden reasoning
# tokens before writing any content. A resume-sized structured answer can use
# well over 20k reasoning tokens, so a low ceiling truncates the response and
# yields empty content with finish_reason=length. This is only an upper clamp;
# the effective value still comes from LLM_MAX_OUTPUT_TOKENS.
MAX_OUTPUT_TOKENS = 65536
TRANSIENT_STATUS_CODES = {408, 425, 429}

# Content-failure classification. These are deliberately distinct from
# transport failures: the content repair/fallback contract owns them, and
# repeating the identical paid request is not the remedy.
OUTPUT_TRUNCATED = "truncated"
OUTPUT_REFUSED = "refused"
OUTPUT_EMPTY = "empty"
OUTPUT_JSON = "json"
OUTPUT_STRUCTURE = "structure"

_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})
_REFUSED_FINISH_REASONS = frozenset({"content_filter", "refusal", "safety"})


class _OutputProblem(Exception):
    """Internal marker for a content-level failure, never a transport failure."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


class _CompletionMessage(BaseModel):
    # An empty body is a distinct content failure, so it must reach our own
    # classification instead of failing generic schema validation.
    content: str = ""
    refusal: str = ""


class _CompletionChoice(BaseModel):
    message: _CompletionMessage
    finish_reason: str = ""


class _CompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _CompletionEnvelope(BaseModel):
    choices: list[_CompletionChoice] = Field(min_length=1)
    usage: _CompletionUsage = Field(default_factory=_CompletionUsage)


class CompatibleLLMProvider:
    def __init__(self, *, transport=None, sleep=None):
        self.transport = transport
        # Injectable so protocol tests do not actually wait for the backoff.
        self._sleep = sleep or asyncio.sleep

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
        if settings.llm_thinking_enabled and _supports_thinking(settings.llm_api_base_url):
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = settings.llm_reasoning_effort or "high"
        max_retries = max(0, settings.llm_max_retries)
        last_error_type = ""
        last_finish_reason = ""
        last_output_kind = ""
        async with httpx.AsyncClient(
            timeout=settings.llm_timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        ) as client:
            for attempt in range(max_retries + 1):
                provider_error: ProviderError | None = None
                cause: Exception | None = None
                try:
                    # A transport retry repeats the same content request. It
                    # MUST NOT append repair instructions: the prompt is part
                    # of the input contract, and a rate limit or network fault
                    # is not a JSON problem.
                    response = await client.post(
                        settings.llm_api_base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json=body,
                    )
                    response.raise_for_status()
                    envelope = _CompletionEnvelope.model_validate(response.json())
                    choice = envelope.choices[0]
                    finish_reason = str(choice.finish_reason or "").strip().lower()
                    last_finish_reason = finish_reason
                    result = _decode_content(
                        raw=choice.message.content,
                        refusal=choice.message.refusal,
                        finish_reason=finish_reason,
                        response_model=response_model,
                    )
                    log_call(
                        task=task,
                        tier=tier,
                        model=model,
                        duration_ms=int((perf_counter() - started_at) * 1000),
                        prompt_tokens=_token_count(envelope.usage.prompt_tokens),
                        completion_tokens=_token_count(envelope.usage.completion_tokens),
                        retried=attempt > 0,
                        error_type=last_error_type,
                        finish_reason=finish_reason,
                    )
                    return result
                except _OutputProblem as exc:
                    # Content problems are never transport retries.
                    last_error_type = "OutputProblem"
                    last_output_kind = exc.kind
                    provider_error = ProviderError(
                        "LLM Provider 返回不可交付的结构化结果",
                        code="LLM_MALFORMED_RESPONSE",
                        retryable=False,
                        output_kind=exc.kind,
                    )
                    cause = exc
                except httpx.HTTPStatusError as exc:
                    last_error_type = type(exc).__name__
                    status_code = exc.response.status_code
                    provider_error = ProviderError(
                        "LLM Provider 请求失败",
                        code="LLM_UPSTREAM_HTTP_ERROR",
                        retryable=status_code in TRANSIENT_STATUS_CODES or status_code >= 500,
                        retry_after_seconds=_retry_after_seconds(exc.response),
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
                    # A syntactically successful response with the wrong
                    # envelope shape is not a transient transport failure.
                    # Retrying it hides a broken provider contract and can
                    # multiply paid calls.
                    last_error_type = type(exc).__name__
                    provider_error = ProviderError(
                        "LLM Provider 返回无效结构化结果",
                        code="LLM_MALFORMED_RESPONSE",
                        retryable=False,
                        output_kind=OUTPUT_STRUCTURE,
                    )
                    cause = exc

                if provider_error.retryable and attempt < max_retries:
                    await self._sleep(
                        _backoff_delay(
                            attempt=attempt,
                            retry_after=provider_error.retry_after_seconds,
                            settings=settings,
                        )
                    )
                    continue
                log_call(
                    task=task,
                    tier=tier,
                    model=model,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    retried=attempt > 0,
                    error_type=last_error_type,
                    finish_reason=last_finish_reason,
                    output_kind=last_output_kind,
                )
                raise provider_error from cause


def _decode_content(*, raw: str, refusal: str, finish_reason: str, response_model):
    """Classify a successful HTTP response by its content, not its status.

    Order matters: a refusal or truncation is reported as such even when the
    partial body would also fail JSON parsing. Providers that omit
    ``finish_reason`` still go through full validation below, so an incomplete
    body is never assumed complete.
    """
    if refusal or finish_reason in _REFUSED_FINISH_REASONS:
        raise _OutputProblem("LLM Provider 拒绝生成该内容", kind=OUTPUT_REFUSED)
    if not str(raw or "").strip():
        raise _OutputProblem("LLM Provider 返回空响应", kind=OUTPUT_EMPTY)
    if finish_reason in _TRUNCATED_FINISH_REASONS:
        raise _OutputProblem("LLM Provider 输出被截断", kind=OUTPUT_TRUNCATED)
    try:
        decoded = loads_lenient(raw)
    except (TypeError, ValueError) as exc:
        raise _OutputProblem(
            "LLM Provider 返回不可解析的结构化内容", kind=OUTPUT_JSON
        ) from exc
    try:
        return response_model.model_validate(decoded)
    except (ValidationError, TypeError, ValueError) as exc:
        raise _OutputProblem(
            "LLM Provider 返回的结构缺少规定字段", kind=OUTPUT_STRUCTURE
        ) from exc


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse Retry-After as delay-seconds or an HTTP date.

    Returns ``None`` when the header is absent or unusable so the caller falls
    back to its own backoff schedule.
    """
    raw = response.headers.get("Retry-After")
    if not raw or not raw.strip():
        return None
    value = raw.strip()
    try:
        seconds = float(value)
    except ValueError:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        seconds = (parsed - datetime.now(UTC)).total_seconds()
    return max(0.0, seconds)


def _backoff_delay(*, attempt: int, retry_after: float | None, settings) -> float:
    """Exponential backoff with jitter, bounded by the configured ceiling.

    An upstream-provided Retry-After takes priority over the local schedule.
    """
    if retry_after is not None:
        return retry_after
    base = max(0.0, settings.llm_retry_backoff_base_seconds)
    ceiling = max(base, settings.llm_retry_backoff_max_seconds)
    exponential = min(ceiling, base * (2**attempt))
    if exponential <= 0:
        return 0.0
    return random.uniform(0.0, exponential)


def _supports_thinking(base_url: str) -> bool:
    """DeepSeek-style thinking fields break other OpenAI-compatible hosts."""
    return "deepseek" in (base_url or "").lower()


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
