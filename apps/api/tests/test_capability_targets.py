import asyncio
from datetime import date
from types import SimpleNamespace

from conftest import docx_file, register
from sqlalchemy import select

from app.models.entities import CapabilityTarget, Job, ResumeFact
from app.providers.llm.schemas import CapabilityPlanOutput
from app.services import capability_service
from app.services.matcher import calculate_experience_months, score_match


def test_must_have_below_half_triggers_hard_block_and_half_does_not():
    fact = SimpleNamespace(
        id="fact-1",
        verification_status="user_confirmed",
        category="skills",
        value_json={"text": "使用 CAD 完成工程图"},
        organization="",
        role_title="",
        source_text="使用 CAD 完成工程图",
        start_date="",
        end_date="",
    )
    job = Job(
        created_by="user",
        company_name="示例公司",
        title="机械工程师",
        raw_jd="要求 CAD、SolidWorks 和 PMP",
        must_have_json=["CAD", "SolidWorks", "PMP"],
        keywords_json=["CAD", "SolidWorks"],
        content_hash="must-have-low",
    )
    result = score_match([fact], job)
    assert result["must_have_hit_rate"] == 1 / 3
    assert result["hard_block"] is True

    job.must_have_json = ["CAD", "SolidWorks"]
    result = score_match([fact], job)
    assert result["must_have_hit_rate"] == 0.5
    assert result["hard_block"] is False


def test_experience_months_are_calculated_from_structured_dates_without_overlap():
    facts = [
        SimpleNamespace(category="employment", start_date="2024-01", end_date="2024-06"),
        SimpleNamespace(category="projects", start_date="2024-05", end_date="2024-09"),
        SimpleNamespace(category="employment", start_date="", end_date="至今"),
    ]
    assert calculate_experience_months(facts, today=date(2026, 8, 11)) == 9


def test_capability_service_discards_non_verbatim_jd_evidence(monkeypatch):
    async def fake_generate_structured(**_kwargs):
        return (
            CapabilityPlanOutput.model_validate(
                {
                    "targets": [
                        {
                            "requirement": "SolidWorks",
                            "category": "skills",
                            "severity": "high",
                            "jd_evidence": "JD 中并不存在的要求",
                            "deliverable": "完成装配体",
                            "acceptance_criteria": ["可打开"],
                            "estimated_hours": 12,
                        }
                    ]
                }
            ),
            "compatible",
        )

    monkeypatch.setattr(capability_service, "generate_structured", fake_generate_structured)
    match = SimpleNamespace(gaps_json=[{"requirement": "SolidWorks"}])
    job = SimpleNamespace(title="机械工程师", raw_jd="要求熟悉 SolidWorks")
    targets, provider = asyncio.run(capability_service.build_targets(match, job, []))
    assert targets == []
    assert provider == "compatible"


def test_capability_target_achievement_creates_confirmed_learned_fact_atomically(client, db):
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    assert client.post(f"/api/resumes/{resume['id']}/confirm-facts").status_code == 200
    job = client.post(
        "/api/jobs/import-text",
        json={
            "company_name": "示例制造公司",
            "title": "机械设计工程师",
            "raw_jd": "负责机械结构设计。\n要求熟悉 SolidWorks 并能输出装配体。",
        },
    ).json()
    match = client.post(
        "/api/matches", json={"resume_id": resume["id"], "job_id": job["id"]}
    ).json()

    created = client.post(f"/api/matches/{match['id']}/capability-targets")
    assert created.status_code == 201, created.text
    targets = created.json()["items"]
    assert targets
    target = next(item for item in targets if "SolidWorks" in item["requirement"])
    repeated = client.post(f"/api/matches/{match['id']}/capability-targets")
    assert repeated.json()["items"][0]["id"] == targets[0]["id"]

    missing = client.patch(
        f"/api/capability-targets/{target['id']}",
        json={"status": "achieved", "evidence_text": ""},
    )
    assert missing.status_code == 422
    achieved = client.patch(
        f"/api/capability-targets/{target['id']}",
        json={
            "status": "achieved",
            "evidence_text": "已提交装配体、工程图和过程说明。",
        },
    )
    assert achieved.status_code == 200, achieved.text
    target_row = db.scalar(select(CapabilityTarget).where(CapabilityTarget.id == target["id"]))
    fact = db.scalar(select(ResumeFact).where(ResumeFact.id == target_row.achieved_fact_id))
    assert target_row.status == "achieved"
    assert fact is not None
    assert fact.provenance == "learned"
    assert fact.verification_status == "user_confirmed"
    assert fact.resume_id == resume["id"]

    listed = client.get(f"/api/capability-targets?job_id={job['id']}&status=achieved")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    client.post("/api/auth/logout")
    register(client, "other@example.test", "其他用户")
    forbidden = client.patch(
        f"/api/capability-targets/{target['id']}",
        json={"status": "achieved", "evidence_text": "尝试访问"},
    )
    assert forbidden.status_code == 404
