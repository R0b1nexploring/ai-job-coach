import asyncio
import logging

import httpcore
import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.providers.jobs import runtime as job_runtime
from app.providers.jobs.public_jsonld import (
    MAX_JSONLD_DEPTH,
    _job_postings,
    _PinnedNetworkBackend,
)
from app.providers.llm import runtime as llm_runtime
from app.providers.llm.base import ProviderError
from app.providers.llm.compatible import CompatibleLLMProvider


class ExampleOutput(BaseModel):
    value: str


def test_malformed_llm_envelope_is_not_retried_and_uses_safe_fallback(monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_api_base_url="https://api.example.test/v1",
        llm_api_key="redacted",
        llm_model_cheap="test-model",
        llm_max_retries=3,
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": []})

    provider = CompatibleLLMProvider(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.providers.llm.compatible.get_settings", lambda: settings)
    monkeypatch.setattr(llm_runtime, "configured_provider", lambda: (provider, "compatible"))

    result, provider_name = asyncio.run(
        llm_runtime.generate_structured(
            task="jd_normalize",
            system_prompt="输出 JSON。",
            user_payload={"mock_response": {"value": "安全本地结果"}},
            response_model=ExampleOutput,
        )
    )

    assert result.value == "安全本地结果"
    assert provider_name == "mock_fallback"
    assert len(requests) == 1


def test_permanent_llm_http_error_is_not_retried(monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_api_base_url="https://api.example.test/v1",
        llm_api_key="redacted",
        llm_model_cheap="test-model",
        llm_max_retries=3,
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": "invalid request"})

    monkeypatch.setattr("app.providers.llm.compatible.get_settings", lambda: settings)
    with pytest.raises(ProviderError) as raised:
        asyncio.run(
            CompatibleLLMProvider(transport=httpx.MockTransport(handler)).generate_structured(
                task="jd_normalize",
                system_prompt="输出 JSON。",
                user_payload={},
                response_model=ExampleOutput,
            )
        )

    assert raised.value.code == "LLM_UPSTREAM_HTTP_ERROR"
    assert raised.value.retryable is False
    assert len(requests) == 1


@pytest.mark.parametrize(
    "error_type",
    [httpx.DecodingError, httpx.UnsupportedProtocol, httpx.ProxyError],
)
def test_all_httpx_request_errors_use_redacted_safe_fallback(
    monkeypatch, caplog, error_type
):
    settings = Settings(
        _env_file=None,
        llm_api_base_url="https://api.example.test/v1",
        llm_api_key="secret-api-key",
        llm_model_cheap="test-model",
        llm_max_retries=0,
    )

    def handler(request):
        raise error_type("raw-upstream-secret", request=request)

    provider = CompatibleLLMProvider(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.providers.llm.compatible.get_settings", lambda: settings)
    monkeypatch.setattr(llm_runtime, "configured_provider", lambda: (provider, "compatible"))
    caplog.set_level(logging.INFO, logger="app.llm")

    result, provider_name = asyncio.run(
        llm_runtime.generate_structured(
            task="jd_normalize",
            system_prompt="sensitive-system-prompt",
            user_payload={
                "resume": "sensitive-resume-body",
                "mock_response": {"value": "安全本地结果"},
            },
            response_model=ExampleOutput,
        )
    )

    assert result.value == "安全本地结果"
    assert provider_name == "mock_fallback"
    assert f"error_type={error_type.__name__}" in caplog.text
    for secret in (
        "secret-api-key",
        "raw-upstream-secret",
        "sensitive-system-prompt",
        "sensitive-resume-body",
    ):
        assert secret not in caplog.text


def test_malformed_job_provider_payload_uses_controlled_sample(monkeypatch):
    class MalformedProvider:
        async def discover(self, **_kwargs):
            return [{"title": "缺少所有必填字段"}]

    monkeypatch.setattr(
        job_runtime,
        "GreenhouseJobProvider",
        lambda _source_key: MalformedProvider(),
    )
    jobs, fallback_used, source_error = asyncio.run(
        job_runtime.discover_jobs(
            provider="greenhouse",
            source_key="valid-source",
            keywords=[],
            cities=[],
            limit=3,
        )
    )

    assert fallback_used is True
    assert source_error == "岗位来源返回无效数据。"
    assert jobs and all(job.provider == "sample" for job in jobs)


def test_public_jsonld_network_backend_connects_to_pinned_address_only():
    class RecordingBackend:
        def __init__(self):
            self.hosts = []

        async def connect_tcp(self, host, _port, **_kwargs):
            self.hosts.append(host)
            return object()

        async def sleep(self, _seconds):
            return None

    recording = RecordingBackend()
    backend = _PinnedNetworkBackend(
        "careers.example.test",
        ["93.184.216.34"],
        backend=recording,
    )

    asyncio.run(backend.connect_tcp("careers.example.test", 443))
    assert recording.hosts == ["93.184.216.34"]
    with pytest.raises(httpcore.ConnectError):
        asyncio.run(backend.connect_tcp("rebound.internal", 443))


def test_public_jsonld_deep_graph_is_rejected_without_python_recursion():
    value: object = {
        "@type": "JobPosting",
        "title": "机械工程师",
        "description": "负责机械设备设计与维护工作。",
    }
    for _index in range(1_200):
        value = [value]

    with pytest.raises(ValueError, match="安全遍历预算"):
        list(_job_postings(value))


def test_public_jsonld_bounded_graph_preserves_document_order():
    first = {"@type": "JobPosting", "title": "岗位一"}
    second = {"@type": ["Thing", "JobPosting"], "title": "岗位二"}
    value: object = [first, {"@graph": [second]}]
    for _index in range(MAX_JSONLD_DEPTH - 3):
        value = [value]

    assert [item["title"] for item in _job_postings(value)] == ["岗位一", "岗位二"]
