from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings

from .base import ProviderError, log_call

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider:
    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> T:
        started_at = perf_counter()
        tier = get_settings().tier_for(task)
        payload = user_payload.get("mock_response", {})
        try:
            result = response_model.model_validate(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            log_call(
                task=task,
                tier=tier,
                model="mock",
                duration_ms=int((perf_counter() - started_at) * 1000),
                error_type=type(exc).__name__,
            )
            raise ProviderError("Mock Provider 返回无效结构化结果") from exc
        log_call(
            task=task,
            tier=tier,
            model="mock",
            duration_ms=int((perf_counter() - started_at) * 1000),
        )
        return result
