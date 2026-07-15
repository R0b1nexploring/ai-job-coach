from typing import Protocol, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    pass


class LLMProvider(Protocol):
    async def generate_structured(
        self, *, task: str, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> T: ...
