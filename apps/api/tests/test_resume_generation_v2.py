import asyncio
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
    MAX_BULLET_CHARS,
    enforce_page_budget,
    estimate_resume_lines,
    evaluate_resume_content,
    generate_guarded_resume,
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

    for bullet in bullets(grown["content_json"]):
        assert len(bullet["text"]) <= MAX_BULLET_CHARS
        assert bullet["text"].startswith(ACTION_PREFIXES)
        assert bullet["source_fact_ids"] or bullet["source_target_ids"]
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
    assert version_b["unachieved_count"] == 0
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
