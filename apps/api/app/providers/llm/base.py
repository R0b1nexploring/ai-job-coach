import logging
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """A redacted provider failure safe to handle outside the provider layer."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "LLM_PROVIDER_ERROR",
        retryable: bool = False,
        output_kind: str = "",
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        # ``output_kind`` classifies the *content* failure (truncated, refused,
        # empty, json, structure) so callers can route it to the content repair
        # contract instead of blindly repeating the same paid request.
        self.output_kind = output_kind
        # Set when the upstream told us how long to wait. Never surfaced to the
        # browser; used only to schedule the next attempt.
        self.retry_after_seconds = retry_after_seconds


logger = logging.getLogger("app.llm")


def log_call(
    *,
    task: str,
    tier: str,
    model: str,
    duration_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    retried: bool = False,
    error_type: str = "",
    finish_reason: str = "",
    output_kind: str = "",
) -> None:
    """Log operational metadata only; never include prompts, payloads, responses, or keys."""
    logger.info(
        "llm_call task=%s tier=%s model=%s duration_ms=%d prompt_tokens=%d "
        "completion_tokens=%d retried=%s error_type=%s finish_reason=%s output_kind=%s",
        task,
        tier,
        model,
        duration_ms,
        prompt_tokens,
        completion_tokens,
        retried,
        error_type or "none",
        finish_reason or "none",
        output_kind or "none",
    )


class LLMProvider(Protocol):
    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> T: ...
