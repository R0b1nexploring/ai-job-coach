import asyncio
import json

import httpx
import pytest
from conftest import docx_file, register

from app.providers.jobs.base import JobProviderError
from app.providers.jobs.catalog import PublicCatalogJobProvider
from app.providers.jobs.greenhouse import GreenhouseJobProvider
from app.providers.jobs.lever import LeverJobProvider
from app.providers.jobs.public_jsonld import PublicJsonLdJobProvider


def test_resume_analysis_and_sample_discovery_loop(client):
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    analysis = client.post(f"/api/resumes/{resume['id']}/analysis")
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["role_suggestions"]
    assert analysis.json()["analysis_status"] == "advisory_not_verified"
    assert analysis.json()["requires_fact_confirmation"] is True

    client.post(f"/api/resumes/{resume['id']}/confirm-facts")
    discovery = client.post(
        "/api/jobs/discover",
        json={"resume_id": resume["id"], "provider": "sample", "limit": 5},
    )
    assert discovery.status_code == 201, discovery.text
    payload = discovery.json()
    assert payload["total"] == 1 and payload["fallback_used"] is False
    assert payload["items"][0]["source_type"] == "sample"
    assert "公开企业招聘接口" in payload["notice"]


def test_external_discovery_requires_source_key(client):
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    response = client.post(
        "/api/jobs/discover",
        json={"resume_id": resume["id"], "provider": "lever"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "JOB_SOURCE_REQUIRED"


def test_external_provider_failure_uses_safe_local_fallback(client):
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    response = client.post(
        "/api/jobs/discover",
        json={"resume_id": resume["id"], "provider": "greenhouse", "source_key": "invalid!"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["items"][0]["discovery_provider"] == "sample"
    assert "Greenhouse" in payload["source_error"]


def test_public_jsonld_api_rejects_unapproved_domain_and_falls_back(client, monkeypatch):
    class EmptyJobSourceSettings:
        @staticmethod
        def allowed_job_source_hosts():
            return set()

    monkeypatch.setattr(
        "app.providers.jobs.runtime.get_settings",
        lambda: EmptyJobSourceSettings(),
    )
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    response = client.post(
        "/api/jobs/discover",
        json={
            "resume_id": resume["id"],
            "provider": "public_jsonld",
            "source_key": "https://careers.example.test/jobs/123",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["items"][0]["discovery_provider"] == "sample"
    assert "JOB_SOURCE_ALLOWED_HOSTS" in payload["source_error"]


def test_greenhouse_provider_reads_only_relevant_public_jobs():
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "设备工程师",
                "location": {"name": "杭州"},
                "absolute_url": "https://example.test/job/1",
                "content": "<p>负责设备点检与 CAD 图纸维护</p>",
            },
            {
                "id": 2,
                "title": "市场经理",
                "location": {"name": "杭州"},
                "absolute_url": "https://example.test/job/2",
                "content": "负责市场活动",
            },
        ]
    }

    def handler(request):
        assert request.url.host == "boards-api.greenhouse.io"
        return httpx.Response(200, json=payload)

    provider = GreenhouseJobProvider("example-company", httpx.MockTransport(handler))
    jobs = asyncio.run(provider.discover(keywords=["设备工程师", "CAD"], cities=["杭州"], limit=10))
    assert [job.title for job in jobs] == ["设备工程师"]
    assert jobs[0].raw_jd == "负责设备点检与 CAD 图纸维护"
    assert jobs[0].published_at is None


def test_lever_provider_preserves_full_jd_and_creation_time():
    payload = [
        {
            "id": "lever-1",
            "text": "Mechanical Engineer",
            "categories": {"location": "Shanghai"},
            "descriptionPlain": "Design mechanical equipment.",
            "lists": [{"text": "Requirements", "content": "<li>CAD</li>"}],
            "additionalPlain": "Work with the project team.",
            "hostedUrl": "https://jobs.lever.co/example/1",
            "createdAt": 1_700_000_000_000,
        }
    ]

    def handler(request):
        return httpx.Response(200, content=json.dumps(payload).encode())

    provider = LeverJobProvider("example", httpx.MockTransport(handler))
    jobs = asyncio.run(provider.discover(keywords=["CAD"], cities=[], limit=10))
    assert len(jobs) == 1
    assert "Design mechanical equipment" in jobs[0].raw_jd
    assert jobs[0].published_at is not None


def test_public_catalog_combines_employer_feeds_and_ranks_preferred_city():
    greenhouse_payload = {
        "jobs": [
            {
                "id": 1,
                "title": "CAD Engineer",
                "location": {"name": "杭州"},
                "absolute_url": "https://example.test/cad",
                "content": "<p>CAD mechanical design</p>",
            }
        ]
    }

    def handler(request):
        if request.url.host == "api.lever.co":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=greenhouse_payload)

    provider = PublicCatalogJobProvider(httpx.MockTransport(handler))
    jobs = asyncio.run(provider.discover(keywords=["CAD"], cities=["杭州"], limit=3))
    assert jobs and jobs[0].city == "杭州"
    assert all(job.matched_keywords == ["CAD"] for job in jobs)


def test_public_jsonld_provider_reads_allowlisted_jobposting():
    job = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "identifier": {"value": "job-123"},
        "title": "机械设备工程师",
        "datePosted": "2026-07-30",
        "hiringOrganization": {"name": "示例制造公司"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "addressLocality": "杭州",
                "addressRegion": "浙江",
                "addressCountry": "中国",
            },
        },
        "description": "<p>负责设备点检、机械改造和 CAD 图纸维护。</p>",
        "qualifications": ["机械工程本科", "能够阅读工程图纸"],
    }
    html = (
        "<html><head><script type=\"application/ld+json\">"
        f"{json.dumps(job, ensure_ascii=False)}"
        "</script></head></html>"
    )

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        assert request.url == "https://careers.example.test/jobs/123"
        return httpx.Response(200, text=html, headers={"Content-Type": "text/html; charset=utf-8"})

    provider = PublicJsonLdJobProvider(
        "https://careers.example.test/jobs/123",
        {"careers.example.test"},
        transport=httpx.MockTransport(handler),
        resolver=lambda _host: ["93.184.216.34"],
    )
    jobs = asyncio.run(provider.discover(keywords=["CAD", "销售"], cities=["杭州"], limit=10))

    assert len(jobs) == 1
    assert jobs[0].external_id == "job-123"
    assert jobs[0].company_name == "示例制造公司"
    assert jobs[0].city == "杭州 · 浙江 · 中国"
    assert jobs[0].matched_keywords == ["CAD"]
    assert jobs[0].published_at is not None
    assert jobs[0].content_quality == "structured_jobposting"


def test_public_jsonld_provider_rejects_unapproved_or_private_hosts():
    with pytest.raises(JobProviderError, match="白名单"):
        PublicJsonLdJobProvider(
            "https://careers.example.test/jobs/123",
            {"other.example.test"},
        )

    provider = PublicJsonLdJobProvider(
        "https://careers.example.test/jobs/123",
        {"*.example.test"},
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        resolver=lambda _host: ["127.0.0.1"],
    )
    with pytest.raises(JobProviderError, match="私有网络"):
        asyncio.run(provider.discover(keywords=[], cities=[], limit=10))


def test_public_jsonld_provider_honors_robots_txt():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /jobs")
        raise AssertionError("robots.txt 禁止后不应读取招聘页")

    provider = PublicJsonLdJobProvider(
        "https://careers.example.test/jobs/123",
        {"careers.example.test"},
        transport=httpx.MockTransport(handler),
        resolver=lambda _host: ["93.184.216.34"],
    )
    with pytest.raises(JobProviderError, match="robots.txt"):
        asyncio.run(provider.discover(keywords=[], cities=[], limit=10))
