from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider:
    async def generate_structured(self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[T]) -> T:
        payload = user_payload.get("mock_response", {})
        return response_model.model_validate(payload)

