import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.providers.llm.base import ProviderError
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm import runtime


class ExampleOutput(BaseModel):
    value: str


def test_configured_provider_failure_uses_structured_mock_fallback(monkeypatch):
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(llm_provider="compatible"))
    result, provider_name = asyncio.run(
        runtime.generate_structured(
            task="test",
            system_prompt="输出严格 JSON。",
            user_payload={"mock_response": {"value": "安全回退"}},
            response_model=ExampleOutput,
        )
    )
    assert result.value == "安全回退"
    assert provider_name == "mock_fallback"


def test_mock_provider_rejects_invalid_structured_output():
    with pytest.raises(ProviderError):
        asyncio.run(
            MockLLMProvider().generate_structured(
                task="test",
                system_prompt="输出严格 JSON。",
                user_payload={"mock_response": {}},
                response_model=ExampleOutput,
            )
        )
