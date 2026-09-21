"""Transport vs. content failure contract for the compatible LLM provider.

Task 17.5: transient failures back off with jitter and honour Retry-After,
transport retries never rewrite the content prompt, and output problems are
classified (truncated / refused / empty / json / structure) instead of being
blindly retried.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.providers.llm.base import ProviderError
from app.providers.llm.compatible import (
    OUTPUT_EMPTY,
    OUTPUT_JSON,
    OUTPUT_REFUSED,
    OUTPUT_STRUCTURE,
    OUTPUT_TRUNCATED,
    CompatibleLLMProvider,
)


class ExampleOutput(BaseModel):
    value: str


def _settings(**overrides) -> Settings:
    values = {
        "llm_api_base_url": "https://api.example.test/v1",
        "llm_api_key": "redacted",
        "llm_model_cheap": "test-model",
        "llm_max_retries": 2,
        # Keep protocol tests instant while still exercising the schedule.
        "llm_retry_backoff_base_seconds": 0.0,
        "llm_retry_backoff_max_seconds": 0.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _run(settings, handler, *, task="jd_normalize"):
    """Run the provider with a recording sleeper."""
    delays: list[float] = []

    async def sleeper(delay):
        delays.append(delay)

    provider = CompatibleLLMProvider(
        transport=httpx.MockTransport(handler), sleep=sleeper
    )
    requests: list[dict] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(request)

    provider.transport = httpx.MockTransport(recording_handler)
    return provider, requests, delays, settings, task


def _call(provider, task):
    return asyncio.run(
        provider.generate_structured(
            task=task,
            system_prompt="原始内容提示词",
            user_payload={"mock_response": {"value": "回退"}},
            response_model=ExampleOutput,
        )
    )


def _success(value="安全结果", finish_reason=None):
    choice = {"message": {"content": json.dumps({"value": value})}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return httpx.Response(200, json={"choices": [choice]})


@pytest.mark.parametrize(
    ("response", "expected_kind"),
    [
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": '{"value": "截断'},
                            "finish_reason": "length",
                        }
                    ]
                },
            ),
            OUTPUT_TRUNCATED,
        ),
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "", "refusal": "拒绝生成"},
                            "finish_reason": "stop",
                        }
                    ]
                },
            ),
            OUTPUT_REFUSED,
        ),
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "   "}, "finish_reason": "stop"}
                    ]
                },
            ),
            OUTPUT_EMPTY,
        ),
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "不是 JSON"},
                            "finish_reason": "stop",
                        }
                    ]
                },
            ),
            OUTPUT_JSON,
        ),
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": '{"other": 1}'},
                            "finish_reason": "stop",
                        }
                    ]
                },
            ),
            OUTPUT_STRUCTURE,
        ),
    ],
)
def test_output_problems_are_classified_and_never_transport_retried(
    monkeypatch, response, expected_kind
):
    settings = _settings()
    provider, requests, delays, _, task = _run(settings, lambda _request: response)
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings", lambda: settings
    )
    with pytest.raises(ProviderError) as raised:
        _call(provider, task)
    assert raised.value.code == "LLM_MALFORMED_RESPONSE"
    assert raised.value.output_kind == expected_kind
    assert raised.value.retryable is False
    # Content problems are handed to the repair/fallback contract instead of
    # repeating the identical paid request.
    assert len(requests) == 1
    assert delays == []


def test_provider_without_finish_reason_still_validates_content(monkeypatch):
    """A missing finish_reason must not be read as "output is complete"."""
    settings = _settings()
    provider, requests, _delays, _, task = _run(
        settings,
        lambda _request: httpx.Response(
            200, json={"choices": [{"message": {"content": '{"value": "完整"}'}}]}
        ),
    )
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings", lambda: settings
    )
    result = _call(provider, task)
    assert result.value == "完整"
    assert len(requests) == 1


def test_transient_failure_retries_with_backoff_and_keeps_the_prompt(
    monkeypatch,
):
    settings = _settings(
        llm_max_retries=2,
        llm_retry_backoff_base_seconds=1.0,
        llm_retry_backoff_max_seconds=30.0,
    )
    attempts = {"count": 0}

    def handler(_request):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, json={"error": "temporary"})
        return _success()

    provider, requests, delays, _, task = _run(settings, handler)
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings", lambda: settings
    )
    result = _call(provider, task)
    assert result.value == "安全结果"
    assert len(requests) == 3
    assert len(delays) == 2
    # Exponential growth, jittered below the ceiling.
    assert 0 <= delays[0] <= 1.0
    assert 0 <= delays[1] <= 2.0
    # Every attempt sends the identical content prompt.
    assert requests[0]["messages"] == requests[1]["messages"] == requests[2]["messages"]


def test_retry_after_seconds_takes_priority_over_local_backoff(monkeypatch):
    settings = _settings(
        llm_max_retries=1,
        llm_retry_backoff_base_seconds=1.0,
        llm_retry_backoff_max_seconds=30.0,
    )
    attempts = {"count": 0}

    def handler(_request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                429, headers={"Retry-After": "7"}, json={"error": "slow down"}
            )
        return _success()

    provider, _requests, delays, _, task = _run(settings, handler)
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings", lambda: settings
    )
    assert _call(provider, task).value == "安全结果"
    assert delays == [7.0]


def test_retry_after_http_date_is_honoured(monkeypatch):
    settings = _settings(
        llm_max_retries=1,
        llm_retry_backoff_base_seconds=1.0,
        llm_retry_backoff_max_seconds=30.0,
    )
    when = datetime.now(UTC) + timedelta(seconds=12)
    attempts = {"count": 0}

    def handler(_request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": format_datetime(when, usegmt=True)},
                json={"error": "slow down"},
            )
        return _success()

    provider, _requests, delays, _, task = _run(settings, handler)
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings", lambda: settings
    )
    assert _call(provider, task).value == "安全结果"
    # Parsed as an HTTP date, allowing for clock skew during the test.
    assert len(delays) == 1
    assert 9.0 <= delays[0] <= 12.0


def test_non_transient_http_error_is_not_retried(monkeypatch):
    settings = _settings()
    provider, requests, delays, _, task = _run(
        settings, lambda _request: httpx.Response(400, json={"error": "bad request"})
    )
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings", lambda: settings
    )
    with pytest.raises(ProviderError) as raised:
        _call(provider, task)
    assert raised.value.code == "LLM_UPSTREAM_HTTP_ERROR"
    assert raised.value.retryable is False
    assert len(requests) == 1
    assert delays == []


def test_output_problem_is_logged_with_reason_and_kind(monkeypatch, caplog):
    settings = _settings(llm_max_retries=0)
    provider, _requests, _delays, _, task = _run(
        settings,
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"value": "半'},
                        "finish_reason": "length",
                    }
                ]
            },
        ),
    )
    monkeypatch.setattr(
        "app.providers.llm.compatible.get_settings", lambda: settings
    )
    caplog.set_level(logging.INFO, logger="app.llm")
    with pytest.raises(ProviderError):
        _call(provider, task)
    assert "finish_reason=length" in caplog.text
    assert f"output_kind={OUTPUT_TRUNCATED}" in caplog.text
    for secret in ("redacted", "原始内容提示词", "半"):
        assert secret not in caplog.text
