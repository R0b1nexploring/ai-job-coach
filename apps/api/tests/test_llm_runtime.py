import asyncio
import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.providers.llm import runtime
from app.providers.llm.base import ProviderError
from app.providers.llm.compatible import CompatibleLLMProvider, _format_instructions
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.schemas import ResumeStructuredV2Output


class ExampleOutput(BaseModel):
    value: str


def test_configured_provider_failure_uses_structured_mock_fallback(monkeypatch):
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(llm_provider="compatible"))
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings",
        lambda: Settings(_env_file=None, llm_api_base_url="", llm_api_key=""),
    )
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


def test_settings_selects_models_by_task_and_keeps_legacy_fallback():
    settings = Settings(
        _env_file=None,
        llm_model="legacy-model",
        llm_model_cheap="cheap-model",
        llm_model_strong="strong-model",
    )
    assert settings.model_for("jd_normalize") == "cheap-model"
    assert settings.model_for("resume_rewrite") == "strong-model"
    assert settings.model_for("unknown_task") == "cheap-model"

    legacy = Settings(
        _env_file=None,
        llm_model="legacy-model",
        llm_model_cheap="",
        llm_model_strong="",
    )
    assert legacy.model_for("jd_normalize") == "legacy-model"
    assert legacy.model_for("resume_rewrite") == "legacy-model"


def test_compatible_provider_uses_task_model_retries_and_logs_no_sensitive_text(
    monkeypatch, caplog
):
    settings = Settings(
        _env_file=None,
        llm_api_base_url="https://api.deepseek.test/v1",
        llm_api_key="secret-api-key",
        llm_model_cheap="cheap-model",
        llm_model_strong="strong-model",
        llm_max_retries=2,
        llm_max_output_tokens=3072,
    )
    monkeypatch.setattr("app.providers.llm.compatible.get_settings", lambda: settings)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '```json\n{"value": "安全结果"}\n```'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    caplog.set_level(logging.INFO, logger="app.llm")
    result = asyncio.run(
        CompatibleLLMProvider(transport=httpx.MockTransport(handler)).generate_structured(
            task="resume_rewrite",
            system_prompt="敏感系统提示",
            user_payload={
                "resume": "完整敏感简历内容",
                "mock_response": {"value": "不得外发的回退内容"},
            },
            response_model=ExampleOutput,
        )
    )

    assert result.value == "安全结果"
    assert len(requests) == 2
    assert requests[-1]["model"] == "strong-model"
    assert requests[-1]["max_tokens"] == 3072
    assert requests[-1]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in requests[-1]["messages"][0]["content"]
    assert "结构示例" in requests[-1]["messages"][0]["content"]
    assert '"value"' in requests[-1]["messages"][0]["content"]
    assert "上一次响应未通过" in requests[-1]["messages"][-1]["content"]
    assert "mock_response" not in requests[-1]["messages"][1]["content"]
    assert "不得外发的回退内容" not in json.dumps(requests[-1], ensure_ascii=False)
    assert "task=resume_rewrite" in caplog.text
    assert "tier=strong" in caplog.text
    assert "prompt_tokens=12" in caplog.text
    assert "completion_tokens=5" in caplog.text
    assert "retried=True" in caplog.text
    assert "error_type=HTTPStatusError" in caplog.text
    for secret in ("secret-api-key", "敏感系统提示", "完整敏感简历内容", "安全结果"):
        assert secret not in caplog.text


def test_resume_schema_example_keeps_new_claims_empty():
    instructions = _format_instructions(ResumeStructuredV2Output)

    assert '"new_claims":[]' in instructions
