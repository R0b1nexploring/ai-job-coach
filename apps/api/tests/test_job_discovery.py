import asyncio
import json

import httpx

from app.providers.jobs.greenhouse import GreenhouseJobProvider
from app.providers.jobs.lever import LeverJobProvider
from app.providers.jobs.catalog import PublicCatalogJobProvider
from conftest import docx_file, register


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
