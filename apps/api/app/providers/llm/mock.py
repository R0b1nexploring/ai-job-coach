from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .base import ProviderError

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider:
    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> T:
        payload = user_payload.get("mock_response", {})
        try:
            return response_model.model_validate(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ProviderError("Mock Provider 返回无效结构化结果") from exc
