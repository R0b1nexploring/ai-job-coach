from conftest import docx_file, register
from sqlalchemy import select

from app.api.routes import workflow
from app.models.entities import ResumeFact, ResumeVersion
from app.providers.llm.schemas import ResumeStructuredV2Output
from app.services.html_resume_renderer import render_resume_html
from app.services.quota_service import change
from app.services.resume_generator import ACTION_PREFIXES, MAX_BULLET_CHARS, estimate_resume_lines


def setup_resume_match(client, db):
    user = register(client)
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
    change(
        db,
        user_id=user["id"],
        quota_type="resume",
        delta=8,
        reason="测试额度",
        idempotency_key="resume-v2-grant",
    )
    db.commit()
    targets = client.post(f"/api/matches/{match['id']}/capability-targets").json()["items"]
    return user, resume, job, match, targets


def bullets(content: dict):
    return [
        bullet
        for section in content.get("sections", [])
        for item in section.get("items", [])
        for bullet in item.get("bullets", [])
    ]


def test_target_and_submittable_versions_use_distinct_sources_and_learned_facts(client, db):
    _user, resume, job, match, targets = setup_resume_match(client, db)
    assert targets
    blueprint = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "target-version"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "target",
        },
    )
    assert blueprint.status_code == 201, blueprint.text
    blueprint = blueprint.json()
    blueprint_bullets = bullets(blueprint["content_json"])
    assert blueprint["kind"] == "target"
    assert blueprint["guard_status"] == "passed"
    assert blueprint["unachieved_count"] == sum(
        bullet["achieved"] is False for bullet in blueprint_bullets
    )
    assert blueprint["unachieved_count"] >= 1

    submittable = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "submittable-before-learning"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    ).json()
    assert submittable["kind"] == "submittable"
    assert submittable["unachieved_count"] == 0
    assert all(not bullet["source_target_ids"] for bullet in bullets(submittable["content_json"]))

    achieved = client.patch(
        f"/api/capability-targets/{targets[0]['id']}",
        json={"status": "achieved", "evidence_text": "已提交可打开的练习文件与过程说明。"},
    ).json()
    learned_fact_id = achieved["achieved_fact_id"]
    grown = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "submittable-after-learning"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    ).json()
    grown_fact_ids = {
        fact_id for bullet in bullets(grown["content_json"]) for fact_id in bullet["source_fact_ids"]
    }
    assert learned_fact_id in grown_fact_ids
    learned = db.scalar(select(ResumeFact).where(ResumeFact.id == learned_fact_id))
    assert learned.provenance == "learned"

    for bullet in bullets(grown["content_json"]):
        assert len(bullet["text"]) <= MAX_BULLET_CHARS
        assert bullet["text"].startswith(ACTION_PREFIXES)
        assert bullet["source_fact_ids"] or bullet["source_target_ids"]
    assert estimate_resume_lines(grown["content_json"]) <= 48


def test_invalid_llm_resume_falls_back_to_deterministic_content(client, db, monkeypatch):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    fact_id = client.get(f"/api/resumes/{resume['id']}/facts").json()["items"][0]["id"]

    async def fake_generate_structured(**_kwargs):
        return (
            ResumeStructuredV2Output.model_validate(
                {
                    "content_version": 2,
                    "kind": "submittable",
                    "headline": "机械设计工程师",
                    "contact": {},
                    "sections": [
                        {
                            "name": "项目经历",
                            "items": [
                                {
                                    "bullets": [
                                        {
                                            "text": "优化流程并提升效率 30%",
                                            "source_fact_ids": [fact_id],
                                            "source_target_ids": [],
                                            "achieved": True,
                                        }
                                    ]
                                }
                            ],
                        }
                    ],
                    "excluded_gaps": [],
                }
            ),
            "compatible",
        )

    monkeypatch.setattr(workflow, "generate_structured", fake_generate_structured)
    response = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "invalid-model-version"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    )
    assert response.status_code == 201, response.text
    version = response.json()
    assert version["fallback_used"] is True
    assert version["traceability_json"]["fallback_reason"] == "model_output_failed_validation"
    assert version["guard_status"] == "passed"
    assert all("30%" not in bullet["text"] for bullet in bullets(version["content_json"]))


def test_v1_resume_content_remains_patchable_and_renderable(client, db):
    user, resume, job, _match, _targets = setup_resume_match(client, db)
    fact = db.scalar(
        select(ResumeFact).where(
            ResumeFact.resume_id == resume["id"],
            ResumeFact.verification_status == "user_confirmed",
        )
    )
    content = {
        "headline": "存量简历",
        "sections": [
            {
                "name": "教育背景",
                "items": [
                    {
                        "text": fact.value_json["text"],
                        "source_fact_ids": [fact.id],
                        "target_requirement_ids": [],
                        "new_claims": [],
                    }
                ],
            }
        ],
        "excluded_gaps": [],
    }
    row = ResumeVersion(
        user_id=user["id"],
        base_resume_id=resume["id"],
        job_id=job["id"],
        title="存量版本",
        content_json=content,
        traceability_json={},
        guard_status="passed",
    )
    db.add(row)
    db.commit()
    content["headline"] = "修改后的存量简历"
    response = client.patch(f"/api/resume-versions/{row.id}", json=content)
    assert response.status_code == 200, response.text
    assert response.json()["content_json"]["headline"] == "修改后的存量简历"
    assert fact.value_json["text"] in render_resume_html(response.json()["content_json"], "备用")
