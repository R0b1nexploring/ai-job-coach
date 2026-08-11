import asyncio
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from conftest import register
from openpyxl import Workbook
from sqlalchemy import select

from app.models.entities import (
    Application,
    ApplicationChannel,
    Job,
    Resume,
    ResumeFact,
    ResumeVersion,
    UserProfile,
)
from app.providers.jobs.base import JobProviderError
from app.providers.jobs.public_jsonld import PublicJsonLdJobProvider
from app.providers.llm.schemas import EmailDraftStructuredOutput
from app.services.application_email import build_email_draft, guard_email_match_points
from app.services.channel_importer import import_channels, read_channel_rows
from app.services.channel_sources import (
    allowed_job_source_hosts,
    invalidate_channel_host_cache,
)


def channel_row(**overrides):
    values = {
        "company_name": "示例制造公司",
        "channel_type": "career_page",
        "url": "https://careers.example.test/jobs",
        "email": "",
        "scope": "both",
        "regions": "杭州，上海",
        "industries": "制造",
        "source_updated_at": "2026-08-01",
    }
    values.update(overrides)
    return values


def test_channel_import_is_idempotent_and_supports_column_mapping(db):
    rows = [{"企业": "示例制造公司", "类型": "email", "地址": "jobs@example.com"}]
    mapping = {"company_name": "企业", "channel_type": "类型", "email": "地址"}

    first = import_channels(
        db,
        rows,
        source="licensed_operator_file",
        execute=True,
        column_map=mapping,
    )
    second = import_channels(
        db,
        rows,
        source="licensed_operator_file",
        execute=True,
        column_map=mapping,
    )

    assert first["new"] == 1 and first["rejected"] == 0
    assert second["updated"] == 1 and second["new"] == 0
    assert len(list(db.scalars(select(ApplicationChannel)))) == 1


def test_channel_import_reads_xlsx_with_mapped_headers(tmp_path):
    path = tmp_path / "licensed-channels.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["企业", "类型", "地址"])
    sheet.append(["示例制造公司", "email", "jobs@example.com"])
    workbook.save(path)

    assert read_channel_rows(path) == [
        {"企业": "示例制造公司", "类型": "email", "地址": "jobs@example.com"}
    ]


def test_channel_import_rejects_domain_resolving_to_private_address(db):
    result = import_channels(
        db,
        [channel_row(url="https://careers.example.com/jobs")],
        source="security-test",
        execute=True,
        resolver=lambda _host: ["10.0.0.7"],
    )

    assert result["rejected_reasons"] == {"url_not_public": 1}
    assert db.scalar(select(ApplicationChannel)) is None


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (channel_row(url="https://127.0.0.1/jobs"), "url_ip_literal_forbidden"),
        (channel_row(url="https://192.168.1.1/jobs"), "url_ip_literal_forbidden"),
        (channel_row(url="https://localhost/jobs"), "url_local_host_forbidden"),
        (channel_row(url="https://foo.internal/jobs"), "url_local_host_forbidden"),
        (channel_row(url="http://careers.example.test/jobs"), "url_requires_https"),
        (
            channel_row(url="https://user:pass@careers.example.test/jobs"),
            "url_userinfo_forbidden",
        ),
        (channel_row(url="https://careers.example.test:8443/jobs"), "url_port_forbidden"),
        (
            channel_row(channel_type="email", url="", email="not-an-email"),
            "invalid_email",
        ),
    ],
)
def test_channel_import_rejects_each_unsafe_value_before_insert(db, row, reason):
    result = import_channels(
        db,
        [row],
        source="security-test",
        execute=True,
        resolver=lambda _host: ["93.184.216.34"],
    )

    assert result["rejected"] == 1
    assert result["rejected_reasons"] == {reason: 1}
    assert db.scalar(select(ApplicationChannel)) is None


def test_channel_host_enters_allowlist_and_dead_feedback_removes_it(client, db):
    register(client)
    channel = ApplicationChannel(
        owner_user_id=None,
        company_name="示例制造公司",
        company_name_normalized="示例制造公司",
        channel_type="career_page",
        url="https://careers.example.test/jobs/123",
        scope="both",
        source="test",
        content_hash=hashlib.sha256(b"channel").hexdigest(),
    )
    db.add(channel)
    db.commit()
    invalidate_channel_host_cache(db)
    assert "careers.example.test" in allowed_job_source_hosts(db)

    job = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "设备工程师",
        "description": "负责设备点检、维护记录与机械改造工作。",
    }
    html = f'<script type="application/ld+json">{json.dumps(job, ensure_ascii=False)}</script>'

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text=html, headers={"Content-Type": "text/html"})

    provider = PublicJsonLdJobProvider(
        channel.url,
        allowed_job_source_hosts(db),
        transport=httpx.MockTransport(handler),
        resolver=lambda _host: ["93.184.216.34"],
    )
    assert asyncio.run(provider.discover(keywords=[], cities=[], limit=5))

    for expected in (1, 2, 3):
        response = client.post(f"/api/channels/{channel.id}/report-dead")
        assert response.status_code == 200
        assert response.json()["dead_reports"] == expected
    assert response.json()["verify_status"] == "dead"
    assert "careers.example.test" not in allowed_job_source_hosts(db)
    with pytest.raises(JobProviderError, match="允许列表"):
        PublicJsonLdJobProvider(channel.url, allowed_job_source_hosts(db))


def test_email_draft_uses_confirmed_facts_and_warns_for_blueprint():
    fact = SimpleNamespace(
        id="fact-1",
        verification_status="user_confirmed",
        category="projects",
        value_json={"text": "使用 CAD 完成机械机构设计"},
        source_text="使用 CAD 完成机械机构设计",
        organization="",
        role_title="",
        label="机械设计项目",
    )
    job = SimpleNamespace(
        title="设备工程师",
        company_name="示例公司",
        must_have_json=["CAD"],
        keywords_json=["机械设计"],
    )
    version = SimpleNamespace(
        title="设备工程师蓝图",
        kind="target",
        unachieved_count=2,
    )
    channel = SimpleNamespace(company_name="示例公司", email="jobs@example.test")
    profile = SimpleNamespace(school="示例大学", major="机械工程")

    result = asyncio.run(
        build_email_draft(
            profile,
            version,
            job,
            channel,
            facts=[fact],
            contact={"name": "小陈", "phone": "13800000000", "email": "chen@example.test"},
        )
    )

    assert result["guard_status"] == "passed"
    assert "使用 CAD 完成机械机构设计" in result["body"]
    assert "未达成" not in " ".join(point["text"] for point in result["match_points"])
    assert any("2 条未达成" in warning for warning in result["warnings"])
    assert any("匹配事实不足 2 条" in warning for warning in result["warnings"])
    assert result["mailto_url"].startswith("mailto:jobs@example.test")


def test_email_draft_ignores_unguarded_llm_framing(monkeypatch):
    async def generated(**_kwargs):
        return (
            EmailDraftStructuredOutput(
                introduction="我拥有十年设备管理经验。",
                match_points=[],
                closing="我已获得高级工程师证书。",
            ),
            "compatible",
        )

    monkeypatch.setattr("app.services.application_email.generate_structured", generated)
    result = asyncio.run(
        build_email_draft(
            SimpleNamespace(school="", major=""),
            SimpleNamespace(title="可投递简历", kind="submittable", unachieved_count=0),
            SimpleNamespace(
                title="设备工程师",
                company_name="示例公司",
                must_have_json=[],
                keywords_json=[],
            ),
            SimpleNamespace(company_name="示例公司", email="jobs@example.test"),
            facts=[],
            contact={"name": "小陈"},
        )
    )

    assert "十年" not in result["body"]
    assert "高级工程师" not in result["body"]


def test_email_guard_rejects_unconfirmed_fact_and_invented_number():
    confirmed = SimpleNamespace(
        id="confirmed",
        verification_status="user_confirmed",
        value_json={"text": "完成设备巡检记录"},
        source_text="完成设备巡检记录",
        organization="",
        role_title="",
    )
    unconfirmed = SimpleNamespace(
        id="pending",
        verification_status="extracted",
        value_json={"text": "使用 Python"},
        source_text="使用 Python",
        organization="",
        role_title="",
    )

    status, issues = guard_email_match_points(
        [
            {"text": "使用 Python", "source_fact_ids": ["pending"]},
            {"text": "设备效率提升 30%", "source_fact_ids": ["confirmed"]},
        ],
        [confirmed, unconfirmed],
    )

    assert status == "blocked"
    assert any("未确认事实" in issue for issue in issues)
    assert any("30%" in issue for issue in issues)


def test_email_guard_rejects_more_than_three_match_points():
    fact = SimpleNamespace(
        id="confirmed",
        verification_status="user_confirmed",
        value_json={"text": "完成设备巡检记录"},
        source_text="完成设备巡检记录",
        organization="",
        role_title="",
    )

    status, issues = guard_email_match_points(
        [{"text": "完成设备巡检记录", "source_fact_ids": ["confirmed"]} for _ in range(4)],
        [fact],
    )

    assert status == "blocked"
    assert "邮件匹配点不能超过 3 条" in issues


def test_email_draft_omits_mailto_when_encoded_body_is_too_long():
    long_text = "完成设备维护记录" * 180
    fact = SimpleNamespace(
        id="fact-long",
        verification_status="user_confirmed",
        category="projects",
        value_json={"text": long_text},
        source_text=long_text,
        organization="",
        role_title="",
        label="长记录",
    )
    result = asyncio.run(
        build_email_draft(
            SimpleNamespace(school="", major=""),
            SimpleNamespace(title="简历", kind="submittable", unachieved_count=0),
            SimpleNamespace(
                title="设备工程师",
                company_name="示例公司",
                must_have_json=[],
                keywords_json=[],
            ),
            SimpleNamespace(company_name="示例公司", email="jobs@example.test"),
            facts=[fact],
            contact={"name": "小陈"},
        )
    )

    assert result["mailto_url"] == ""
    assert any("复制主题和正文" in warning for warning in result["warnings"])


def test_application_email_draft_api_uses_linked_channel(client, db):
    user = register(client)
    profile = db.get(UserProfile, user["id"])
    profile.school = "示例大学"
    profile.major = "机械工程"
    resume = Resume(
        user_id=user["id"],
        original_file_key="test-resume.docx",
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="resume.docx",
        parse_status="parsed",
        contact_json={"name": "小陈", "email": "chen@example.test"},
    )
    job = Job(
        created_by=user["id"],
        company_name="示例公司",
        title="设备工程师",
        raw_jd="负责设备点检和机械设计工作。",
        keywords_json=["机械设计"],
        content_hash="job-email-draft",
    )
    channel = ApplicationChannel(
        company_name="示例公司",
        company_name_normalized="示例公司",
        channel_type="email",
        email="jobs@example.test",
        source="test",
        content_hash=hashlib.sha256(b"email-channel").hexdigest(),
    )
    db.add_all([resume, job, channel])
    db.flush()
    fact = ResumeFact(
        resume_id=resume.id,
        user_id=user["id"],
        category="projects",
        label="机械设计",
        value_json={"text": "完成机械机构设计"},
        source_text="完成机械机构设计",
        verification_status="user_confirmed",
        created_by=user["id"],
    )
    version = ResumeVersion(
        user_id=user["id"],
        base_resume_id=resume.id,
        job_id=job.id,
        title="可投递简历",
        kind="submittable",
        content_json={},
        traceability_json={},
        guard_status="passed",
        review_status="approved",
    )
    db.add_all([fact, version])
    db.flush()
    application = Application(
        user_id=user["id"],
        job_id=job.id,
        resume_version_id=version.id,
        channel_id=channel.id,
    )
    db.add(application)
    db.commit()

    response = client.post(f"/api/applications/{application.id}/email-draft")

    assert response.status_code == 200, response.text
    assert response.json()["to"] == "jobs@example.test"
    assert response.json()["guard_status"] == "passed"
