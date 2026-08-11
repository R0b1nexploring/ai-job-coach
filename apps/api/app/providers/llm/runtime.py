from pydantic import BaseModel

from app.config import get_settings

from .base import ProviderError
from .compatible import CompatibleLLMProvider
from .mock import MockLLMProvider


def configured_provider():
    provider_name = get_settings().llm_provider.strip().lower()
    if provider_name == "compatible":
        return CompatibleLLMProvider(), "compatible"
    if provider_name == "mock":
        return MockLLMProvider(), "mock"
    if provider_name == "mock_fallback":
        return MockLLMProvider(), "mock_fallback"
    return MockLLMProvider(), "mock_fallback"


async def generate_structured[T: BaseModel](
    *,
    task: str,
    system_prompt: str,
    user_payload: dict,
    response_model: type[T],
) -> tuple[T, str]:
    """Run the configured provider and safely fall back to deterministic local output."""
    provider, provider_name = configured_provider()
    try:
        result = await provider.generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_model=response_model,
        )
        return result, provider_name
    except ProviderError:
        if provider_name in {"mock", "mock_fallback"}:
            raise
        fallback = await MockLLMProvider().generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_model=response_model,
        )
        return fallback, "mock_fallback"
