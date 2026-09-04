import asyncio
import re
from types import SimpleNamespace

import pytest
from conftest import docx_file, register
from sqlalchemy import select

from app.models.entities import ResumeFact, ResumeVersion, StorageDeletionTask
from app.providers.llm.schemas import ResumeStructuredV2Output
from app.providers.storage.local import LocalStorage
from app.services.html_resume_renderer import render_resume_html
from app.services.quota_service import change
from app.services.resume_generator import (
    ACTION_PREFIXES,
    JD_GAP_SECTION,
    MAX_BULLET_CHARS,
    enforce_page_budget,
    estimate_resume_lines,
    evaluate_resume_content,
    generate_guarded_resume,
    generate_resume,
)


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


def grounded_content(*, headline="机械设计工程师", contact=None, text="参与机械机构设计"):
    return {
        "content_version": 2,
        "kind": "submittable",
        "headline": headline,
        "contact": contact or {},
        "sections": [
            {
                "name": "项目经历",
                "items": [
                    {
                        "organization": "",
                        "role_title": "",
                        "location": "",
                        "start_date": "",
                        "end_date": "",
                        "bullets": [
                            {
                                "text": text,
                                "source_fact_ids": ["fact-1"],
                                "source_target_ids": [],
                                "achieved": True,
                                "new_claims": [],
                            }
                        ],
                    }
                ],
            }
        ],
        "excluded_gaps": [],
    }


def grounded_fact():
    return SimpleNamespace(
        id="fact-1",
        verification_status="user_confirmed",
        category="projects",
        label="机械设计项目",
        value_json={"text": "参与机械机构设计"},
        source_text="参与机械机构设计",
        organization="",
        role_title="",
        location="",
        start_date="",
        end_date="",
        provenance="original_resume",
    )


def test_resume_guard_rejects_forged_headline_and_contact_but_allows_presentation_wrapper():
    expected_contact = {
        "name": "小陈",
        "phone": "13800000000",
        "email": "chen@example.test",
        "city": "杭州",
    }
    forged = evaluate_resume_content(
        grounded_content(
            headline="十年经验高级工程师",
            contact={
                "name": "伪造姓名",
                "phone": "13999999999",
                "email": "fake@example.test",
                "city": "北京",
            },
        ),
        [grounded_fact()],
        [],
        kind="submittable",
        expected_headline="机械设计工程师",
        expected_contact=expected_contact,
    )

    assert forged["status"] == "blocked"
    assert "简历标题包含未经来源支持的职业主张" in forged["issues"]
    assert "简历联系方式与已确认的原始简历信息不一致" in forged["issues"]

    reasonable = evaluate_resume_content(
        grounded_content(
            headline="机械设计工程师岗位定制简历",
            contact=expected_contact,
        ),
        [grounded_fact()],
        [],
        kind="submittable",
        expected_headline="机械设计工程师",
        expected_contact=expected_contact,
    )
    assert reasonable["status"] == "passed"


@pytest.mark.parametrize(
    "claim",
    [
        "参与机械机构设计交付",
        "参与机械机构设计实现商业化",
        "参与机械机构设计业内领先",
        "参与机械机构设计全面达标",
    ],
)
def test_resume_guard_rejects_short_unsupported_chinese_suffixes(claim):
    result = evaluate_resume_content(
        grounded_content(text=claim),
        [grounded_fact()],
        [],
        kind="submittable",
        expected_headline="机械设计工程师",
        expected_contact={},
    )

    assert result["status"] == "blocked"
    assert any("中文主张" in issue for issue in result["issues"])


def test_generated_resume_falls_back_to_confirmed_contact_when_llm_forges_identity(monkeypatch):
    expected_contact = {
        "name": "小陈",
        "phone": "13800000000",
        "email": "chen@example.test",
        "city": "杭州",
    }
    calls = 0

    async def generated(**_kwargs):
        nonlocal calls
        calls += 1
        return (
            ResumeStructuredV2Output.model_validate(
                grounded_content(
                    headline="十年经验高级工程师",
                    contact={
                        "name": "伪造姓名",
                        "phone": "13999999999",
                        "email": "fake@example.test",
                        "city": "北京",
                    },
                )
            ),
            "compatible",
        )

    monkeypatch.setattr("app.services.resume_generator.generate_structured", generated)
    result = asyncio.run(
        generate_guarded_resume(
            [grounded_fact()],
            SimpleNamespace(
                title="机械设计工程师",
                company_name="示例公司",
                must_have_json=[],
                keywords_json=[],
            ),
            [],
            kind="submittable",
            contact=expected_contact,
        )
    )

    assert calls == 2
    assert result["fallback_used"] is True
    assert result["evaluation"]["status"] == "passed"
    assert result["content"]["headline"] == "机械设计工程师"
    assert result["content"]["contact"] == expected_contact


def test_page_budget_preserves_at_least_one_blueprint_target():
    content = {
        "content_version": 2,
        "kind": "target",
        "sections": [
            {
                "name": "项目经历",
                "items": [
                    {
                        "bullets": [
                            {
                                "text": "完成" + "机械设计记录" * 7,
                                "source_fact_ids": [f"fact-{index}"],
                                "source_target_ids": [],
                                "achieved": True,
                            }
                            for index in range(30)
                        ]
                        + [
                            {
                                "text": "完成 PLC 调试练习",
                                "source_fact_ids": [],
                                "source_target_ids": ["target-1"],
                                "achieved": False,
                            }
                        ]
                    }
                ],
            }
        ],
    }

    result = enforce_page_budget(content)

    assert estimate_resume_lines(result) <= 48
    assert any(bullet["source_target_ids"] for bullet in bullets(result))


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
        fact_id
        for bullet in bullets(grown["content_json"])
        for fact_id in bullet["source_fact_ids"]
    }
    assert learned_fact_id in grown_fact_ids
    learned = db.scalar(select(ResumeFact).where(ResumeFact.id == learned_fact_id))
    assert learned.provenance == "learned"

    skill_names = {
        section["name"]
        for section in grown["content_json"].get("sections", [])
        if section.get("presentation") == "tags" or section.get("name") in {"技能", "技能证书"}
    }
    for section in grown["content_json"].get("sections", []):
        tag_section = section.get("presentation") == "tags" or section.get("name") in {"技能", "技能证书"}
        for bullet in bullets({"sections": [section]}):
            assert len(bullet["text"]) <= MAX_BULLET_CHARS
            assert bullet["source_fact_ids"] or bullet["source_target_ids"]
            if tag_section:
                assert not bullet["text"].startswith(("掌握", "熟悉", "了解", "精通"))
            else:
                assert bullet["text"].startswith(ACTION_PREFIXES)
    assert skill_names <= {"技能", "技能证书"}
    assert estimate_resume_lines(grown["content_json"]) <= 48


def test_invalid_llm_resume_falls_back_to_deterministic_content(client, db, monkeypatch):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    fact_items = client.get(f"/api/resumes/{resume['id']}/facts").json()["items"]
    fact_id = next(item["id"] for item in fact_items if "CAD" in str(item.get("value_json") or {}))

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

    monkeypatch.setattr(
        "app.services.resume_generator.generate_structured", fake_generate_structured
    )
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
    assert version["traceability_json"]["semantic_retry_used"] is True
    assert version["guard_status"] == "passed"
    assert all("30%" not in bullet["text"] for bullet in bullets(version["content_json"]))


def test_target_resume_falls_back_when_model_omits_all_learning_targets(client, db, monkeypatch):
    _user, resume, job, match, targets = setup_resume_match(client, db)
    assert targets
    fact_id = client.get(f"/api/resumes/{resume['id']}/facts").json()["items"][0]["id"]

    async def fake_generate_structured(**_kwargs):
        return (
            ResumeStructuredV2Output.model_validate(
                {
                    "content_version": 2,
                    "kind": "target",
                    "headline": "机械设计工程师",
                    "contact": {},
                    "sections": [
                        {
                            "name": "项目经历",
                            "items": [
                                {
                                    "bullets": [
                                        {
                                            "text": "完成 CAD 机械机构设计",
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

    monkeypatch.setattr(
        "app.services.resume_generator.generate_structured", fake_generate_structured
    )
    response = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "target-without-target-source"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "target",
        },
    )

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["fallback_used"] is True
    assert version["traceability_json"]["semantic_retry_used"] is True
    assert version["unachieved_count"] >= 1
    assert any(bullet["source_target_ids"] for bullet in bullets(version["content_json"]))


def test_target_resume_retries_once_after_semantic_validation_failure(client, db, monkeypatch):
    _user, resume, job, match, targets = setup_resume_match(client, db)
    fact_items = client.get(f"/api/resumes/{resume['id']}/facts").json()["items"]
    fact_id = next(item["id"] for item in fact_items if "CAD" in str(item.get("value_json") or {}))
    target_id = targets[0]["id"]
    calls = []

    async def fake_generate_structured(**kwargs):
        calls.append(kwargs["user_payload"])
        target_bullets = []
        if len(calls) == 2:
                target_bullets.append(
                    {
                        "text": "完成一个可展示练习",
                    "source_fact_ids": [],
                    "source_target_ids": [target_id],
                    "achieved": False,
                }
            )
        return (
            ResumeStructuredV2Output.model_validate(
                {
                    "content_version": 2,
                    "kind": "target",
                    "headline": "机械设计工程师",
                    "contact": {},
                    "sections": [
                        {
                            "name": "项目经历",
                            "items": [
                                {
                                    "bullets": [
                                        {
                                            "text": "使用 CAD 完成机械机构设计",
                                            "source_fact_ids": [fact_id],
                                            "source_target_ids": [],
                                            "achieved": True,
                                        },
                                        *target_bullets,
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

    monkeypatch.setattr(
        "app.services.resume_generator.generate_structured", fake_generate_structured
    )
    response = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "target-semantic-retry"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "target",
        },
    )

    assert response.status_code == 201, response.text
    version = response.json()
    assert len(calls) == 2
    assert calls[1]["previous_output_rejected"] is True
    assert "蓝图简历未包含任何未达成学习目标" in calls[1]["validation_feedback"]
    assert version["fallback_used"] is False, version["traceability_json"]
    assert version["guard_status"] == "passed"
    assert version["traceability_json"]["semantic_retry_used"] is True


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


def test_v2_resume_patch_rejects_content_over_single_page_budget(client, db):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    version = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "page-budget-version"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    ).json()
    fact = db.scalar(
        select(ResumeFact).where(
            ResumeFact.resume_id == resume["id"],
            ResumeFact.verification_status == "user_confirmed",
        )
    )
    oversized = {
        "content_version": 2,
        "kind": "submittable",
        "headline": "机械设计工程师",
        "contact": {},
        "sections": [
            {
                "name": f"经历 {index}",
                "items": [
                    {
                        "bullets": [
                            {
                                "text": str(fact.value_json["text"]),
                                "source_fact_ids": [fact.id],
                                "source_target_ids": [],
                                "achieved": True,
                                "new_claims": [],
                            }
                        ]
                    }
                ],
            }
            for index in range(50)
        ],
        "excluded_gaps": [],
    }

    response = client.patch(f"/api/resume-versions/{version['id']}", json=oversized)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "RESUME_PAGE_BUDGET_EXCEEDED"
    assert error["details"]["estimated_lines"] > error["details"]["max_lines"]


def test_target_and_interview_sources_are_isolated_by_match(client, db):
    user, _resume_a, job, _match_a, targets_a = setup_resume_match(client, db)
    assert targets_a
    resume_b = client.post(
        "/api/resumes",
        files=docx_file(),
    ).json()
    assert client.post(f"/api/resumes/{resume_b['id']}/confirm-facts").status_code == 200
    change(
        db,
        user_id=user["id"],
        quota_type="match",
        delta=1,
        reason="第二份简历匹配测试额度",
        idempotency_key="second-match-grant",
    )
    db.commit()
    match_b = client.post(
        "/api/matches", json={"resume_id": resume_b["id"], "job_id": job["id"]}
    ).json()
    version_b = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "match-b-target-version"},
        json={
            "base_resume_id": resume_b["id"],
            "job_id": job["id"],
            "match_id": match_b["id"],
            "kind": "target",
        },
    )
    assert version_b.status_code == 201, version_b.text
    version_b = version_b.json()
    assert version_b["match_id"] == match_b["id"]
    assert version_b["unachieved_count"] >= 1
    assert version_b["content_json"]["sections"][0]["name"] == JD_GAP_SECTION
    assert not {
        target_id
        for bullet in bullets(version_b["content_json"])
        for target_id in bullet["source_target_ids"]
    }.intersection({target["id"] for target in targets_a})

    foreign_target_content = {
        "content_version": 2,
        "kind": "target",
        "headline": "机械设计工程师",
        "contact": {},
        "sections": [
            {
                "name": "学习目标",
                "items": [
                    {
                        "bullets": [
                            {
                                "text": "完成一个可展示练习",
                                "source_fact_ids": [],
                                "source_target_ids": [targets_a[0]["id"]],
                                "achieved": False,
                                "new_claims": [],
                            }
                        ]
                    }
                ],
            }
        ],
        "excluded_gaps": [],
    }
    edited = client.patch(
        f"/api/resume-versions/{version_b['id']}", json=foreign_target_content
    )
    assert edited.status_code == 200
    assert edited.json()["guard_status"] == "blocked"
    assert any(
        "学习目标" in issue
        for issue in edited.json()["traceability_json"]["new_claims"]
    )

    row = db.get(ResumeVersion, version_b["id"])
    row.content_json = version_b["content_json"]
    row.guard_status = "passed"
    row.review_status = "approved"
    row.unachieved_count = 0
    change(
        db,
        user_id=user["id"],
        quota_type="interview",
        delta=1,
        reason="来源隔离测试额度",
        idempotency_key="match-source-interview-grant",
    )
    db.commit()
    interview = client.post(
        "/api/interviews",
        headers={"Idempotency-Key": "match-source-interview"},
        json={"job_id": job["id"], "resume_version_id": version_b["id"]},
    )
    assert interview.status_code == 201, interview.text
    assert interview.json()["question_set_json"]["exposure_warning"]["items"] == []


def test_resume_edit_does_not_delete_cached_export_before_database_commit(
    client, db, monkeypatch
):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    version = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "edit-export-order"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    ).json()
    row = db.get(ResumeVersion, version["id"])
    storage = LocalStorage()
    row.export_file_key = storage.save(b"old export", ".docx")
    old_export_key = row.export_file_key
    db.commit()
    deleted: list[str] = []
    monkeypatch.setattr(LocalStorage, "delete", lambda _self, key: deleted.append(key))
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit")))

    with pytest.raises(RuntimeError, match="commit"):
        client.patch(f"/api/resume-versions/{row.id}", json=version["content_json"])

    assert deleted == []
    assert storage.path(old_export_key).exists()
    db.rollback()


def test_resume_edit_failed_export_deletion_remains_retryable(client, db, monkeypatch):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    version = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "edit-export-retry"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    ).json()
    row = db.get(ResumeVersion, version["id"])
    storage = LocalStorage()
    row.export_file_key = storage.save(b"private old export", ".docx")
    old_export_key = row.export_file_key
    db.commit()

    def fail_delete(_self, _key):
        raise OSError("temporary storage outage")

    monkeypatch.setattr(LocalStorage, "delete", fail_delete)
    response = client.patch(
        f"/api/resume-versions/{row.id}",
        json=version["content_json"],
    )

    assert response.status_code == 200, response.text
    assert db.get(ResumeVersion, row.id).export_file_key == ""
    assert storage.path(old_export_key).exists()
    assert db.scalar(
        select(StorageDeletionTask).where(
            StorageDeletionTask.file_key == old_export_key
        )
    ) is not None


def test_missing_docx_cache_is_regenerated(client, db):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    version = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "missing-export-cache"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    ).json()
    row = db.get(ResumeVersion, version["id"])
    row.guard_status = "passed"
    row.review_status = "approved"
    row.export_file_key = "missing-cache.docx"
    db.commit()

    response = client.get(f"/api/resume-versions/{row.id}/download")

    assert response.status_code == 200
    db.refresh(row)
    assert row.export_file_key != "missing-cache.docx"
    assert LocalStorage().path(row.export_file_key).exists()


def test_owner_can_preview_and_download_after_guard_without_advisor(client, db):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    version = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "owner-download-draft"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["id"]
    assert version.json()["review_status"] == "draft"
    preview = client.get(f"/api/resume-versions/{version_id}/preview")
    assert preview.status_code == 200
    download = client.get(f"/api/resume-versions/{version_id}/download")
    assert download.status_code == 200
    blocked = client.post(
        "/api/applications",
        json={"job_id": job["id"], "resume_version_id": version_id},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "RESUME_NOT_APPROVED"


def test_deterministic_resume_splits_star_clauses_without_ellipsis():
    fact = SimpleNamespace(
        id="fact-1",
        verification_status="user_confirmed",
        category="projects",
        label="去核机课程设计",
        value_json={"text": "完成红枣去核机传动与执行机构设计。负责机构方案，并输出 CAD 图纸。"},
        source_text="完成红枣去核机传动与执行机构设计。负责机构方案，并输出 CAD 图纸。",
        organization="示例大学",
        role_title="项目负责人",
        location="杭州",
        start_date="2024-03",
        end_date="2024-06",
        provenance="original_resume",
    )
    job = SimpleNamespace(
        title="机械设计工程师",
        company_name="示例制造公司",
        must_have_json=["CAD"],
        keywords_json=["机械"],
    )

    content = generate_resume([fact], job, kind="submittable")
    texts = [bullet["text"] for bullet in bullets(content)]

    assert all("…" not in text for text in texts)
    assert any("CAD" in text and "图纸" in text for text in texts)
    assert any("设计" in text for text in texts)
    assert all(len(text) <= MAX_BULLET_CHARS for text in texts)
    assert all(text.startswith(ACTION_PREFIXES) for text in texts)
    assert any("并输出 CAD 图纸" in text or "输出 CAD 图纸" in text for text in texts)
    project_section = next(section for section in content["sections"] if section["name"] == "项目经历")
    assert project_section["items"][0]["organization"] == "示例大学"


def test_experience_library_facts_appear_in_generated_resume(client, db):
    _user, resume, job, match, _targets = setup_resume_match(client, db)
    created = client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": "巡检台账练习",
            "organization": "用户自己的实习工厂",
            "role_title": "实习生",
            "summary": "整理设备点检记录并核对 CAD 图纸尺寸。",
            "bullets_json": ["整理点检记录"],
            "skills_json": ["设备点检"],
        },
    )
    assert created.status_code == 201, created.text
    version = client.post(
        "/api/resume-versions",
        headers={"Idempotency-Key": "library-fact-resume"},
        json={
            "base_resume_id": resume["id"],
            "job_id": job["id"],
            "match_id": match["id"],
            "kind": "submittable",
        },
    )
    assert version.status_code == 201, version.text
    texts = " ".join(bullet["text"] for bullet in bullets(version.json()["content_json"]))
    organizations = [
        item.get("organization", "")
        for section in version.json()["content_json"]["sections"]
        for item in section.get("items", [])
    ]
    assert "用户自己的实习工厂" in organizations or "点检" in texts


def _confirmed_fact(**overrides):
    payload = {
        "verification_status": "user_confirmed",
        "source_text": "",
        "organization": "",
        "role_title": "",
        "location": "",
        "start_date": "",
        "end_date": "",
        "provenance": "original_resume",
    }
    payload.update(overrides)
    payload.setdefault("label", payload.get("value_json", {}).get("text", "经历"))
    payload.setdefault("source_text", payload.get("value_json", {}).get("text", ""))
    return SimpleNamespace(**payload)


def test_job_template_puts_experience_before_education_and_keeps_skills_as_tags():
    education = _confirmed_fact(
        id="edu-1",
        category="education",
        label="机械工程本科",
        value_json={"text": "示例大学机械工程本科"},
        organization="示例大学",
        role_title="机械工程本科",
        start_date="2021-09",
        end_date="2025-06",
    )
    project = _confirmed_fact(
        id="proj-1",
        category="projects",
        label="去核机课程设计",
        value_json={"text": "完成红枣去核机传动与执行机构设计，并输出 CAD 图纸。"},
        organization="示例大学",
        role_title="项目负责人",
        start_date="2024-03",
        end_date="2024-06",
    )
    skill = _confirmed_fact(
        id="skill-1",
        category="skills",
        label="机械设计软件",
        value_json={"text": "掌握 SolidWorks、AutoCAD、GD&T"},
    )
    job = SimpleNamespace(
        title="机械设计工程师",
        company_name="示例制造公司",
        must_have_json=["SolidWorks", "CAD"],
        keywords_json=["机械"],
    )

    content = generate_resume([project, skill, education], job, kind="submittable")
    names = [section["name"] for section in content["sections"]]

    assert names.index("项目经历") < names.index("教育背景")
    assert names.index("教育背景") < names.index("技能证书")
    skill_section = next(section for section in content["sections"] if section["name"] == "技能证书")
    assert skill_section["presentation"] == "tags"
    skill_texts = [bullet["text"] for bullet in bullets({"sections": [skill_section]})]
    assert skill_texts == ["SolidWorks", "AutoCAD", "GD&T"]
    assert all("掌握" not in text for text in skill_texts)
    assert all(not text.startswith(ACTION_PREFIXES) for text in skill_texts)

    evaluation = evaluate_resume_content(
        content,
        [education, project, skill],
        [],
        kind="submittable",
        expected_headline="机械设计工程师",
        expected_contact={},
    )
    assert evaluation["status"] == "passed", evaluation["issues"]

    html = render_resume_html(content, "备用")
    assert "SolidWorks / AutoCAD / GD&amp;T" in html or "SolidWorks / AutoCAD / GD&T" in html
    assert re.search(r'class="skill-tags">[^<]*SolidWorks / AutoCAD', html)
    assert "掌握了建模能力" not in html
    assert "项目负责人｜示例大学｜2024.03–2024.06" in html
    assert "示例大学｜机械工程本科｜2021.09–2025.06" in html


def test_blueprint_leads_with_jd_gaps_and_explains_mismatch():
    fact = grounded_fact()
    target = SimpleNamespace(
        id="target-sw",
        requirement="SolidWorks",
        category="skills",
        severity="high",
        status="pending",
        deliverable="完成一个含装配体的 SolidWorks 练习并导出工程图",
        jd_evidence="要求熟悉 SolidWorks 并能输出装配体。",
    )
    job = SimpleNamespace(
        title="机械设计工程师",
        company_name="示例制造公司",
        must_have_json=["SolidWorks"],
        keywords_json=["机械"],
        raw_jd="负责机械结构设计。\n要求熟悉 SolidWorks 并能输出装配体。",
    )
    match = SimpleNamespace(
        recommendation="低优先",
        dimension_scores_json={"hard_requirements": 0},
        gaps_json=[{"requirement": "SolidWorks", "action": "完成练习"}],
        ai_explanation_json={"summary": "硬性工具要求未覆盖。"},
    )

    content = generate_resume([fact], job, [target], kind="target", match=match)

    assert content["sections"][0]["name"] == JD_GAP_SECTION
    gap_bullets = bullets({"sections": [content["sections"][0]]})
    assert gap_bullets
    assert all(bullet["achieved"] is False for bullet in gap_bullets)
    assert all(bullet["source_target_ids"] for bullet in gap_bullets)
    assert content["gap_summary"]["reasons"]
    assert any("SolidWorks" in reason for reason in content["gap_summary"]["reasons"])
    evaluation = evaluate_resume_content(content, [fact], [target], kind="target")
    assert evaluation["status"] == "passed"
