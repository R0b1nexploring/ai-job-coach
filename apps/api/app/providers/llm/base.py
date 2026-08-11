import logging
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    pass


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
) -> None:
    """Log operational metadata only; never include prompts, payloads, responses, or keys."""
    logger.info(
        "llm_call task=%s tier=%s model=%s duration_ms=%d prompt_tokens=%d "
        "completion_tokens=%d retried=%s error_type=%s",
        task,
        tier,
        model,
        duration_ms,
        prompt_tokens,
        completion_tokens,
        retried,
        error_type or "none",
    )


class LLMProvider(Protocol):
    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> T: ...
