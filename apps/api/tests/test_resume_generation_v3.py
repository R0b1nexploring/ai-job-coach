import asyncio
import io
import json
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import httpx
from conftest import docx_file, register
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.config import Settings
from app.database import make_engine
from app.errors import AppError
from app.models.entities import InterviewGuide, QuotaReservation, ResumeBundle, ResumeBundleRun, ResumeFact, ResumeVersion, User, now
from app.providers.llm.base import ProviderError
from app.providers.llm.compatible import CompatibleLLMProvider
from app.providers.llm.runtime import generate_structured as real_generate_structured
from app.services.bundle_service import _apply_pair_result, build_project_story_inputs, build_writing_brief, claim_bundle_run
from app.services.content_contract import iter_project_stories, normalize_bullet, validate_content
from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html
from app.services.pdf_export import converter_available, inspect_pdf_bytes
from app.services.quality_service import apply_critic_cannot_override, evaluate_version
from app.services.quota_service import balance, change
from app.services.resume_style import BLUEPRINT_FOOTER
from app.services.resume_template import template_snapshot


def _grant_resume_quota(db, user_id, key="resume-v3-grant"):
    change(
        db,
        user_id=user_id,
        quota_type="resume",
        delta=8,
        reason="测试额度",
        idempotency_key=key,
    )
    db.commit()


def _confirm_material(client, *, title, organization, summary, extra=None):
    payload = {
        "kind": "project",
        "title": title,
        "organization": organization,
        "role_title": "课程负责人",
        "summary": summary,
        "details_json": {
            "actions": summary,
            "tools": extra or title,
            "results": "完成记录",
            "ownership": "本人完成",
        },
    }
    material = client.post("/api/experience", json=payload).json()
    confirmed = client.post(f"/api/experience/{material['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def _import_job(client):
    job = client.post(
        "/api/jobs/import-text",
        json={
            "company_name": "示例制造公司",
            "title": "机械设计工程师",
            "raw_jd": "负责机械结构设计。\n要求熟悉 SolidWorks 并能输出装配体。",
        },
    )
    assert job.status_code in {200, 201}, job.text
    profile = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job.json()["id"]]},
    )
    assert profile.status_code == 201, profile.text
    return job.json(), profile.json()


def setup_bundle(client, db):
    user = register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    assert client.post(f"/api/resumes/{resume['id']}/confirm-facts").status_code == 200
    _confirm_material(
        client,
        title="装配体课程设计",
        organization="用户自己的实验室",
        summary="使用 SolidWorks 完成装配体建模并输出工程图",
        extra="SolidWorks",
    )
    _job, profile = _import_job(client)
    _grant_resume_quota(db, user["id"])
    return user, resume, profile


def setup_blank_user(client, db):
    user = register(client, email="blank@example.test")
    _confirm_material(
        client,
        title="装配体课程设计",
        organization="用户自己的实验室",
        summary="使用 SolidWorks 完成装配体建模并输出工程图",
        extra="SolidWorks",
    )
    _job, profile = _import_job(client)
    _grant_resume_quota(db, user["id"], key="resume-blank-grant")
    return user, profile


def process_created_bundle(client, payload, key):
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["status"] == "queued"
    assert body.get("versions") in ({}, None) or body["versions"] == {}
    processed = client.post(f"/api/resume-bundles/{body['id']}/process")
    assert processed.status_code == 202, processed.text
    return created.json(), processed.json()


def _bullets(content):
    rows = []
    for section in content.get("sections") or []:
        for item_index, item in enumerate(section.get("items") or []):
            for bullet_index, bullet in enumerate(item.get("bullets") or []):
                rows.append(
                    {
                        "section": section.get("name"),
                        "item_index": item_index,
                        "bullet_index": bullet_index,
                        "organization": item.get("organization"),
                        "bullet": bullet,
                    }
                )
    return rows


def test_writing_brief_selects_three_relevant_materials_stably():
    facts = [
        SimpleNamespace(id="f-a", material_id="material-a", category="projects", label="CAD 图纸", organization="实验室", role_title="成员", value_json={"text": "使用 CAD 输出工程图"}, source_text="", claim_type="tool", evidence_json={}),
        SimpleNamespace(id="f-b", material_id="material-b", category="projects", label="装配体", organization="实验室", role_title="成员", value_json={"text": "使用 SolidWorks 完成装配体建模"}, source_text="", claim_type="tool", evidence_json={}),
        SimpleNamespace(id="f-c", material_id="material-c", category="projects", label="数据分析", organization="实验室", role_title="成员", value_json={"text": "使用 Python 清洗实验数据"}, source_text="", claim_type="tool", evidence_json={}),
        SimpleNamespace(id="f-d", material_id="material-d", category="projects", label="夹具设计", organization="实验室", role_title="成员", value_json={"text": "用 SolidWorks 绘制夹具模型"}, source_text="", claim_type="tool", evidence_json={}),
    ]
    requirements = [
        {"id": "r-solidworks", "text": "熟悉 SolidWorks", "priority": "high", "frequency": 1, "sources": [{"job_id": "j1", "evidence": "熟悉 SolidWorks"}]}
    ]
    brief = build_writing_brief(facts, [], requirements, [{"job_id": "j1", "company_name": "示例公司", "title": "机械设计工程师"}])
    assert [item["id"] for item in brief["selected_materials"]] == ["material-b", "material-d", "material-a"]
    assert brief["per_job"][0]["selected_materials"][0]["matched_requirement_ids"] == ["r-solidworks"]
    assert brief["selected_fact_ids"] == ["f-a", "f-b", "f-d"]


def test_writing_brief_keeps_experience_claims_isolated_and_handles_empty_materials():
    facts = [
        SimpleNamespace(id="f-one-action", material_id="material-one", category="projects", label="项目一", organization="实验室甲", role_title="成员", value_json={"text": "使用 SolidWorks 建模"}, source_text="", claim_type="action", evidence_json={"source_field": "action"}),
        SimpleNamespace(id="f-one-result", material_id="material-one", category="projects", label="项目一", organization="实验室甲", role_title="成员", value_json={"text": "输出工程图"}, source_text="", claim_type="result", evidence_json={"source_field": "result"}),
        SimpleNamespace(id="f-two", material_id="material-two", category="projects", label="项目二", organization="实验室乙", role_title="成员", value_json={"text": "使用 Python 分析数据"}, source_text="", claim_type="tool", evidence_json={"source_field": "tool"}),
    ]
    requirements = [{"id": "r", "text": "熟悉 SolidWorks", "priority": "high", "frequency": 1, "sources": []}]
    brief = build_writing_brief(
        facts,
        [{"id": "draft-one", "kind": "project", "title": "待确认项目", "organization": "个人", "role_title": "", "summary": "尝试 SolidWorks", "details": {"tools": "SolidWorks"}}],
        requirements,
        [],
    )
    confirmed = next(item for item in brief["selected_materials"] if item["id"] == "material-one")
    assert confirmed["fact_ids"] == ["f-one-action", "f-one-result"]
    assert confirmed["organization"] == "实验室甲"
    assert any(item["source"] == "draft_material" and item["id"] == "draft-one" for item in brief["selected_materials"])
    assert build_writing_brief([], [], requirements, [])["selected_materials"] == []


def test_project_story_inputs_handle_multiple_and_blank_materials_without_cross_project_facts():
    facts = [
        SimpleNamespace(id="f-one", material_id="m-one", category="projects", label="项目甲", organization="实验室甲", role_title="成员", value_json={"text": "用 SolidWorks 输出装配图"}, source_text="", claim_type="action", evidence_json={}),
        SimpleNamespace(id="f-two", material_id="m-two", category="projects", label="项目乙", organization="实验室乙", role_title="成员", value_json={"text": "用 Python 整理实验数据"}, source_text="", claim_type="action", evidence_json={}),
    ]
    requirements = [
        {"id": "r-cad", "text": "SolidWorks 装配设计", "priority": "high", "frequency": 1, "sources": []},
        {"id": "r-data", "text": "Python 数据处理", "priority": "medium", "frequency": 1, "sources": []},
    ]
    rows = build_project_story_inputs(facts, [], requirements, [])
    assert {tuple(row["fact_ids"]) for row in rows} >= {("f-one",), ("f-two",)}
    assert all(len(row["fact_ids"]) <= 1 for row in rows)
    blank = build_project_story_inputs([], [], requirements, [])
    assert blank == [{
        "id": "virtual:target-project", "schema_version": 1, "source": "virtual_target",
        "title": "目标实践方案",
        "organization": "", "role_title": "计划负责人", "fact_ids": [],
        "material_summary": "", "material_details": {},
        "requirement_ids": ["r-cad"], "requirements": ["SolidWorks 装配设计"],
        "story_boundary": "这是待完成的蓝图项目；所有结果都是目标，不能陈述为个人既有经历",
        "design_supplement": (
            "无个人素材；围绕目标要求设计边界清楚的小项目，"
            "信息不足时缩小范围，方法、步骤与验证方式要具体，所有结果为 target。"
        ),
    }]


def test_v3_bullet_contract_preserves_new_claims():
    bullet = normalize_bullet({"text": "完成点检", "new_claims": ["补充点检成果"]})
    assert bullet["new_claims"] == ["补充点检成果"]


def test_create_bundle_returns_queued_and_is_idempotent(client, db):
    user, resume, profile = setup_bundle(client, db)
    payload = {"base_resume_id": resume["id"], "target_profile_id": profile["id"]}
    first = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-1"},
        json=payload,
    )
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "queued"
    listed = client.get("/api/resume-bundles")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == first.json()["id"]
    replay = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-1"},
        json=payload,
    )
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["status"] == "queued"
    bundles = list(db.scalars(select(ResumeBundle).where(ResumeBundle.user_id == user["id"])))
    assert len(bundles) == 1
    processed = client.post(f"/api/resume-bundles/{first.json()['id']}/process")
    assert processed.status_code == 202, processed.text
    body = processed.json()
    assert body["status"] in {"ready", "degraded"}
    assert set(body["versions"]) == {"submittable", "target"}
    versions = list(db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == body["id"])))
    assert {row.kind for row in versions} == {"submittable", "target"}
    sub = next(row for row in versions if row.kind == "submittable")
    tgt = next(row for row in versions if row.kind == "target")
    assert sub.content_json["content_version"] == 3
    sub_texts = [row["bullet"]["text"] for row in _bullets(sub.content_json)]
    tgt_gaps = [
        row["bullet"]
        for row in _bullets(tgt.content_json)
        if row["bullet"].get("achieved") is False
        and (row["bullet"].get("requirement_ids") or row["bullet"].get("source_target_ids"))
    ]
    if tgt_gaps:
        assert all(bullet.get("requirement_ids") for bullet in tgt_gaps)
        assert all(bullet["text"] not in sub_texts for bullet in tgt_gaps)


def test_patch_accepts_v3_studio_content_and_keeps_bullet_ids(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-patch-v3",
    )
    version_id = processed["versions"]["submittable"]["id"]
    studio = client.get(f"/api/resume-versions/{version_id}/studio")
    assert studio.status_code == 200, studio.text
    content = studio.json()["content_json"]
    original_ids = [row["bullet"]["id"] for row in _bullets(content)]
    content["headline"] = (content.get("headline") or "机械设计工程师") + " · 修订"
    patched = client.patch(f"/api/resume-versions/{version_id}", json=content)
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["content_json"]["content_version"] == 3
    assert body["guard_status"] == "passed"
    assert [row["bullet"]["id"] for row in _bullets(body["content_json"])] == original_ids
    invalid_format = client.get(
        f"/api/resume-versions/{version_id}/studio-download?format=exe"
    )
    assert invalid_format.status_code == 422
    exported = client.get("/api/account/export")
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload["target_profiles"]
    assert payload["resume_bundles"]
    assert payload["experience_entries"]
    assert payload["interview_guides"]


def test_new_user_blank_material_generates_without_old_resume(client, db):
    _user, profile = setup_blank_user(client, db)
    created, processed = process_created_bundle(
        client,
        {"target_profile_id": profile["id"]},
        "bundle-blank",
    )
    assert created["status"] == "queued"
    assert processed["status"] in {"ready", "degraded"}
    assert set(processed["versions"]) == {"submittable", "target"}


def _compatible_settings(**overrides):
    values = {
        "_env_file": None,
        "app_env": "test",
        "llm_provider": "compatible",
        "llm_api_base_url": "https://api.example.test/v1",
        "llm_api_key": "test-key",
        "llm_model_cheap": "cheap-model",
        "llm_model_strong": "strong-model",
        "llm_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


def _install_compatible_provider(monkeypatch, handler):
    settings = _compatible_settings()
    provider = CompatibleLLMProvider(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.providers.llm.compatible.get_settings", lambda: settings)
    monkeypatch.setattr("app.providers.llm.runtime.configured_provider", lambda: (provider, "compatible"))
    return provider


def _structured_llm_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 12},
        },
    )


def _is_resume_copy_payload(payload: dict) -> bool:
    if payload.get("pair"):
        return True
    if payload.get("kind") not in {"submittable", "target"} or "facts" not in payload:
        return False
    if "bullets" in payload or "profile_title" in payload or "hard_passed" in payload:
        return False
    return True


def _pair_rewrite_output(payload: dict) -> dict:
    submittable = _rewrite_output_from_payload({**payload, "kind": "submittable"})
    target = _rewrite_output_from_payload({**payload, "kind": "target"})
    target["sections"][0]["items"][0]["bullets"].extend(
        {
            "text": requirement["text"],
            "source_fact_ids": [],
            "source_target_ids": [requirement["id"]],
            "requirement_ids": [requirement["id"]],
            "achieved": False,
            "new_claims": [],
        }
        for requirement in payload.get("requirements") or []
        if requirement.get("id") and requirement.get("text")
    )
    return {"submittable": submittable, "target": target}


def _resume_copy_response(payload: dict) -> httpx.Response | None:
    if not _is_resume_copy_payload(payload):
        return None
    if payload.get("pair"):
        return _structured_llm_response(_pair_rewrite_output(payload))
    return _structured_llm_response(_rewrite_output_from_payload(payload))


def _rewrite_output_from_payload(payload: dict) -> dict:
    facts = list(payload.get("facts") or [])
    fact = facts[0] if facts else {}
    return {
        "content_version": 3,
        "kind": payload.get("kind") or "submittable",
        "headline": payload.get("headline") or "机械设计工程师",
        "contact": payload.get("contact") or {},
        "sections": [
            {
                "name": "项目/科研/竞赛",
                "presentation": "items",
                "items": [
                    {
                        "organization": fact.get("organization") or "用户自己的实验室",
                        "role_title": fact.get("role_title") or "课程负责人",
                        "location": "",
                        "start_date": "",
                        "end_date": "",
                        "bullets": [
                            {
                                "text": (fact.get("text") or "使用 SolidWorks 完成装配体")[:80],
                                "source_fact_ids": [fact["id"]] if fact.get("id") else [],
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


def test_real_provider_receives_facts_and_requirements(client, db, monkeypatch):
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        captured.append(payload)
        written = _resume_copy_response(payload)
        if written is not None:
            return written
        if "hard_passed" in payload:
            return _structured_llm_response({"dimensions": {}, "summary": "ok"})
        return _structured_llm_response(
            {
                "kind": payload.get("kind") or "submittable",
                "cards": [],
                "self_intro_60s": "",
                "self_intro_90s": "",
                "jd_questions": [],
                "motivation": "",
                "questions_to_ask": [],
                "checklist": [],
            }
        )

    _install_compatible_provider(monkeypatch, handler)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-real-provider",
    )
    rewrite_payloads = [item for item in captured if _is_resume_copy_payload(item)]
    assert rewrite_payloads, captured
    assert len(rewrite_payloads) == 1
    assert processed["status"] in {"ready", "degraded"}
    assert processed["generation_metadata_json"]["writer"]["submittable"] == "model"
    assert processed["generation_metadata_json"]["writer"]["target"] == "model"
    for payload in rewrite_payloads:
        assert "mock_response" not in payload
        assert payload.get("pair") is True
        assert payload["facts"], payload
        assert any(item.get("text") for item in payload["facts"])
        assert payload["requirements"]
        assert any(item.get("text") for item in payload["requirements"])
        assert all("frequency" in item and "sources" in item for item in payload["requirements"])
        assert payload["job_context"]
        assert payload["job_context"][0]["raw_jd"] == "负责机械结构设计。\n要求熟悉 SolidWorks 并能输出装配体。"
        assert payload["job_context"][0]["company_name"] == "示例制造公司"
        assert payload["writing_brief"]["selection_version"] == 1
        assert payload["writing_brief"]["selected_materials"]
        assert all("claim_type" in item and "evidence_json" in item for item in payload["facts"])
        assert payload["headline"]


def test_real_provider_failure_is_degraded_not_model_success(client, db, monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream unavailable"})

    _install_compatible_provider(monkeypatch, handler)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-real-provider-fail",
    )
    assert processed["status"] == "degraded"
    assert processed["status"] != "ready"
    assert processed["generation_metadata_json"]["degraded"] is True
    assert processed["generation_metadata_json"]["writer"]["submittable"] == "fallback"
    assert processed["generation_metadata_json"]["writer"]["target"] == "fallback"
    report = client.get(
        f"/api/resume-versions/{processed['versions']['submittable']['id']}/studio"
    ).json()["quality_report_json"]
    assert report["reviewer"] == "deterministic"
    assert report["critic_unavailable"] is True
    assert "确定性检查" in report["reviewer_note"]


def test_initial_critic_failure_is_explicitly_degraded(client, db, monkeypatch):
    async def fail_critic(*, task, system_prompt, user_payload, response_model):
        assert task == "resume_quality"
        raise ProviderError("critic unavailable")

    monkeypatch.setattr("app.services.quality_service.generate_structured", fail_critic)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-critic-failure",
    )
    assert processed["status"] == "degraded"
    assert "critic_unavailable_deterministic_fallback" in processed["generation_metadata_json"]["repair_history"]
    report = client.get(
        f"/api/resume-versions/{processed['versions']['submittable']['id']}/studio"
    ).json()["quality_report_json"]
    assert report["reviewer"] == "deterministic"
    assert report["critic_unavailable"] is True


def test_initial_generation_calls_writer_once_for_both_kinds(client, db, monkeypatch):
    calls = []

    async def capture(*, task, system_prompt, user_payload, response_model):
        calls.append(task)
        return await real_generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_model=response_model,
        )

    monkeypatch.setattr("app.services.bundle_service.generate_structured", capture)
    monkeypatch.setattr("app.services.quality_service.generate_structured", capture)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-one-write",
    )
    assert processed["status"] in {"ready", "degraded"}
    assert calls.count("resume_rewrite") == 1
    assert calls.count("resume_quality") == 2
    assert set(processed["versions"]) == {"submittable", "target"}


def test_quality_failure_records_bounded_repair_history(client, db, monkeypatch):
    from app.services.quality_service import evaluate_version as real_evaluate

    calls = {"count": 0}

    def fail_once_then_evaluate(**kwargs):
        calls["count"] += 1
        report = real_evaluate(**kwargs)
        if calls["count"] == 1:
            report["hard_passed"] = False
            report["status"] = "blocked"
            report["issues"] = ["测试质量问题"]
        return report

    monkeypatch.setattr("app.services.bundle_service.evaluate_version", fail_once_then_evaluate)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-quality-repair",
    )
    assert processed["status"] == "degraded"
    history = processed["generation_metadata_json"]["repair_history"]
    assert any(str(item).startswith("repair_submittable:") for item in history)
    version = client.get(
        f"/api/resume-versions/{processed['versions']['submittable']['id']}/studio"
    ).json()
    assert version["quality_report_json"]["repair_history"] == history


def test_quality_repair_that_passes_is_ready_and_keeps_history(client, db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        written = _resume_copy_response(payload)
        if written is not None:
            return written
        if "hard_passed" in payload:
            return _structured_llm_response({"dimensions": {}, "summary": "ok"})
        if "bullets" in payload:
            return _structured_llm_response({"kind": payload.get("kind") or "submittable", "cards": []})
        return _structured_llm_response({"kind": payload.get("kind") or "submittable", "cards": []})

    _install_compatible_provider(monkeypatch, handler)
    from app.services.quality_service import evaluate_version as real_evaluate

    calls = {"count": 0}

    def fail_once(**kwargs):
        calls["count"] += 1
        report = real_evaluate(**kwargs)
        if calls["count"] == 1:
            report["hard_passed"] = False
            report["status"] = "blocked"
            report["issues"] = ["测试质量问题"]
        return report

    monkeypatch.setattr("app.services.bundle_service.evaluate_version", fail_once)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-quality-repair-ready",
    )
    assert processed["status"] == "ready"
    assert calls["count"] == 4
    history = processed["generation_metadata_json"]["repair_history"]
    assert len(history) == 1
    assert history[0].startswith("repair_submittable:")
    assert processed["generation_metadata_json"]["degraded"] is False


def test_changed_materials_create_new_bundle_without_client_key(client, db):
    _user, resume, profile = setup_bundle(client, db)
    payload = {"base_resume_id": resume["id"], "target_profile_id": profile["id"]}
    first = client.post("/api/resume-bundles", json=payload)
    assert first.status_code == 202, first.text
    processed = client.post(f"/api/resume-bundles/{first.json()['id']}/process")
    assert processed.status_code == 202, processed.text
    assert processed.json()["status"] in {"ready", "degraded"}
    _confirm_material(
        client,
        title="PLC 点检练习",
        organization="用户自己的车间",
        summary="跟随师傅完成 PLC 点检并记录报警代码",
        extra="PLC",
    )
    second = client.post("/api/resume-bundles", json=payload)
    assert second.status_code == 202, second.text
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["status"] == "queued"
    listed = client.get("/api/resume-bundles").json()["items"]
    assert {item["id"] for item in listed} >= {first.json()["id"], second.json()["id"]}
    original = client.get(f"/api/resume-bundles/{first.json()['id']}").json()
    assert original["status"] in {"ready", "degraded"}
    assert original["run"]["status"] in {"ready", "degraded"}


def test_same_materials_without_key_replay_existing_bundle(client, db):
    _user, resume, profile = setup_bundle(client, db)
    payload = {"base_resume_id": resume["id"], "target_profile_id": profile["id"]}
    first = client.post("/api/resume-bundles", json=payload)
    replay = client.post("/api/resume-bundles", json=payload)
    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]


def test_worker_uses_the_generation_input_snapshot(client, db):
    user, resume, profile = setup_bundle(client, db)
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-snapshot"},
        json={"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
    )
    assert created.status_code == 202
    fact = db.scalar(
        select(ResumeFact).where(
            ResumeFact.user_id == user["id"],
            ResumeFact.verification_status == "user_confirmed",
        )
    )
    original_text = (fact.value_json or {}).get("text")
    fact.value_json = {"text": "后来修改的内容，不应进入已经排队的任务"}
    flag_modified(fact, "value_json")
    db.commit()
    processed = client.post(f"/api/resume-bundles/{created.json()['id']}/process")
    assert processed.status_code == 202
    version = client.get(
        f"/api/resume-versions/{processed.json()['versions']['submittable']['id']}/studio"
    ).json()
    texts = [row["bullet"]["text"] for row in _bullets(version["content_json"])]
    assert original_text in texts
    assert "后来修改的内容" not in texts


def test_failed_bundle_releases_reserved_quota(client, db, monkeypatch):
    user, resume, profile = setup_bundle(client, db)
    before = balance(db, user["id"], "resume")

    async def hard_failure(_inputs):
        return {"status": "failed", "error": "hard_gates_failed", "repair_history": []}

    monkeypatch.setattr("app.services.bundle_service._compose_pair", hard_failure)
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-refund"},
        json={"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
    )
    processed = client.post(f"/api/resume-bundles/{created.json()['id']}/process")
    assert processed.json()["status"] == "failed"
    assert balance(db, user["id"], "resume") == before
    reservation = db.scalar(
        select(QuotaReservation).where(
            QuotaReservation.resource_type == "resume_bundle",
            QuotaReservation.resource_id == created.json()["id"],
        )
    )
    assert reservation is not None
    assert reservation.status == "refunded"


def test_regeneration_provider_failure_is_visible_and_retryable(client, db, monkeypatch):
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-regenerate-error",
    )
    version_id = processed["versions"]["submittable"]["id"]
    detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
    bullet_id = _bullets(detail["content_json"])[0]["bullet"]["id"]

    async def unavailable(**_kwargs):
        raise ProviderError("provider unavailable")

    monkeypatch.setattr("app.services.bundle_service.generate_structured", unavailable)
    response = client.post(
        f"/api/resume-versions/{version_id}/regenerate",
        json={"scope": "bullet", "bullet_id": bullet_id},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RESUME_REGENERATION_UNAVAILABLE"


def test_explicit_idempotency_key_still_rejects_changed_materials(client, db):
    _user, resume, profile = setup_bundle(client, db)
    payload = {"base_resume_id": resume["id"], "target_profile_id": profile["id"]}
    first = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "fixed-client-key"},
        json=payload,
    )
    assert first.status_code == 202, first.text
    _confirm_material(
        client,
        title="PLC 点检练习",
        organization="用户自己的车间",
        summary="跟随师傅完成 PLC 点检并记录报警代码",
        extra="PLC",
    )
    reused = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "fixed-client-key"},
        json=payload,
    )
    assert reused.status_code == 409, reused.text
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_queued_bundle_with_ready_run_is_reconciled(client, db):
    _user, resume, profile = setup_bundle(client, db)
    payload = {"base_resume_id": resume["id"], "target_profile_id": profile["id"]}
    created = client.post("/api/resume-bundles", json=payload)
    assert created.status_code == 202, created.text
    processed = client.post(f"/api/resume-bundles/{created.json()['id']}/process")
    assert processed.status_code == 202, processed.text
    assert processed.json()["status"] in {"ready", "degraded"}
    bundle = db.get(ResumeBundle, created.json()["id"])
    bundle.status = "queued"
    db.flush()
    replay = client.post("/api/resume-bundles", json=payload)
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == created.json()["id"]
    assert replay.json()["status"] in {"ready", "degraded"}
    assert replay.json()["run"]["status"] in {"ready", "degraded"}
    db.refresh(bundle)
    assert bundle.status in {"ready", "degraded"}


def test_model_failure_delivers_degraded_not_ready(client, db, monkeypatch):
    async def fail_writer(*, task, system_prompt, user_payload, response_model):
        if task == "resume_rewrite":
            raise ProviderError("model unavailable")
        return await real_generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_model=response_model,
        )

    monkeypatch.setattr("app.services.bundle_service.generate_structured", fail_writer)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-degraded",
    )
    assert processed["status"] == "degraded"
    assert processed["status"] != "ready"
    assert processed["generation_metadata_json"]["degraded"] is True
    assert processed["generation_metadata_json"]["writer"]["submittable"] == "fallback"


def test_degraded_version_can_be_previewed_without_leaking_status_to_resume(client, db, monkeypatch):
    async def fail_writer(*, task, system_prompt, user_payload, response_model):
        if task == "resume_rewrite":
            raise ProviderError("model unavailable")
        return await real_generate_structured(
            task=task,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_model=response_model,
        )

    monkeypatch.setattr("app.services.bundle_service.generate_structured", fail_writer)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-degraded-preview",
    )
    version_id = processed["versions"]["submittable"]["id"]
    preview = client.get(f"/api/resume-versions/{version_id}/studio-preview")
    assert preview.status_code == 200
    assert "基础降级版本" not in preview.text
    assert client.get(f"/api/resume-versions/{version_id}/studio-download?format=html").status_code == 200
    assert client.get(f"/api/resume-versions/{version_id}/studio-download?format=docx").status_code == 200


def test_quality_hard_gate_blocks_studio_preview_even_when_guard_flag_is_stale(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-quality-export-gate",
    )
    version = db.get(ResumeVersion, processed["versions"]["submittable"]["id"])
    version.guard_status = "passed"
    version.quality_report_json = {"hard_passed": False, "status": "blocked", "issues": ["版面失败"]}
    db.commit()
    blocked = client.get(f"/api/resume-versions/{version.id}/studio-preview")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "RESUME_QUALITY_GATE_BLOCKED"


def test_local_quality_gate_bypass_is_degraded_and_keeps_fact_guard(client, db, monkeypatch):
    disabled = Settings(
        _env_file=None,
        app_env="development",
        resume_quality_gate_enabled=False,
    )
    monkeypatch.setattr("app.services.bundle_service.get_settings", lambda: disabled)
    monkeypatch.setattr("app.api.routes.studio.get_settings", lambda: disabled)
    from app.services.quality_service import evaluate_version as real_evaluate

    def fail_quality(**kwargs):
        report = real_evaluate(**kwargs)
        report["hard_passed"] = False
        report["status"] = "blocked"
        report["issues"] = ["测试质量问题"]
        return report

    monkeypatch.setattr("app.services.bundle_service.evaluate_version", fail_quality)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-quality-gate-bypassed",
    )
    assert processed["status"] == "degraded"
    assert processed["generation_metadata_json"]["quality_gate_bypassed"] is True
    assert processed["generation_metadata_json"]["degraded"] is True
    version_id = processed["versions"]["submittable"]["id"]
    detail = client.get(f"/api/resume-versions/{version_id}/studio")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["guard_status"] == "passed"
    assert body["quality_report_json"]["status"] == "bypassed"
    assert body["quality_report_json"]["hard_passed"] is False
    assert client.get(f"/api/resume-versions/{version_id}/studio-preview").status_code == 200


def test_scoped_regen_keeps_non_first_bullet_fact_ownership(client, db):
    user = register(client, email="scoped@example.test")
    first = _confirm_material(
        client,
        title="装配体课程设计",
        organization="用户自己的实验室",
        summary="使用 SolidWorks 完成装配体建模",
        extra="SolidWorks",
    )
    second = _confirm_material(
        client,
        title="PLC 点检练习",
        organization="用户自己的车间",
        summary="跟随师傅完成 PLC 点检并记录报警代码",
        extra="PLC",
    )
    _job, profile = _import_job(client)
    _grant_resume_quota(db, user["id"], key="resume-scoped-grant")
    _created, processed = process_created_bundle(
        client,
        {"target_profile_id": profile["id"]},
        "bundle-scoped",
    )
    version_id = processed["versions"]["submittable"]["id"]
    detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
    rows = _bullets(detail["content_json"])
    owned = [row for row in rows if row["bullet"].get("source_fact_ids")]
    assert len(owned) >= 2
    first_bullet = owned[0]["bullet"]
    second_bullet = owned[1]["bullet"]
    assert first_bullet["source_fact_ids"] != second_bullet["source_fact_ids"]
    regenerated = client.post(
        f"/api/resume-versions/{version_id}/regenerate",
        json={"scope": "bullet", "bullet_id": second_bullet["id"]},
    )
    assert regenerated.status_code == 200, regenerated.text
    after = _bullets(regenerated.json()["content_json"])
    after_first = next(row["bullet"] for row in after if row["bullet"]["id"] == first_bullet["id"])
    after_second = next(row["bullet"] for row in after if row["bullet"]["id"] == second_bullet["id"])
    assert after_first["source_fact_ids"] == first_bullet["source_fact_ids"]
    assert set(after_second["source_fact_ids"]) == set(second_bullet["source_fact_ids"])
    assert after_second["text"] != first_bullet["text"]
    _ = (first, second)


def test_lock_persists_and_full_regen_keeps_position(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-lock",
    )
    version_id = processed["versions"]["submittable"]["id"]
    detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
    rows = _bullets(detail["content_json"])
    target = rows[0]
    bullet = target["bullet"]
    locked = client.post(
        f"/api/resume-versions/{version_id}/lock",
        json={"bullet_id": bullet["id"], "locked": True},
    )
    assert locked.status_code == 200, locked.text
    reread = client.get(f"/api/resume-versions/{version_id}/studio").json()
    reread_bullet = next(row["bullet"] for row in _bullets(reread["content_json"]) if row["bullet"]["id"] == bullet["id"])
    assert reread_bullet["locked"] is True
    regenerated = client.post(
        f"/api/resume-versions/{version_id}/regenerate",
        json={"scope": "all"},
    )
    assert regenerated.status_code == 200, regenerated.text
    after_rows = _bullets(regenerated.json()["content_json"])
    matches = [row for row in after_rows if row["bullet"]["id"] == bullet["id"]]
    assert len(matches) == 1
    kept = matches[0]
    assert kept["bullet"]["text"] == bullet["text"]
    assert kept["bullet"]["locked"] is True
    assert kept["section"] == target["section"]
    assert kept["organization"] == target["organization"]
    assert kept["item_index"] == target["item_index"]
    assert kept["bullet_index"] == target["bullet_index"]
    assert sum(1 for row in after_rows if row["bullet"]["text"] == bullet["text"]) == 1
    guides = list(db.scalars(select(InterviewGuide).where(InterviewGuide.bundle_id == processed["id"])))
    assert guides
    if regenerated.json()["content_hash"] != processed["versions"]["submittable"]["content_hash"]:
        assert any(guide.status == "stale" for guide in guides)
        stale = next(guide for guide in guides if guide.status == "stale")
        refreshed = client.post(f"/api/interview-guides/{stale.id}/regenerate")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "ready"
        assert refreshed.json()["content_hash"] == regenerated.json()["content_hash"]


def test_reorder_persists_within_the_same_experience(client, db):
    from copy import deepcopy

    from app.services.content_contract import new_bullet_id

    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-reorder",
    )
    version_id = processed["versions"]["submittable"]["id"]
    version = db.get(ResumeVersion, version_id)
    content = deepcopy(version.content_json or {})
    item = next(
        row
        for section in content.get("sections") or []
        for row in section.get("items") or []
        if isinstance(row, dict)
    )
    if len(item.get("bullets") or []) < 2:
        extra = deepcopy(item["bullets"][0])
        extra["id"] = new_bullet_id()
        extra["text"] = f"{extra.get('text') or '要点'}（第二条）"
        extra["locked"] = False
        item["bullets"].append(extra)
        version.content_json = content
        flag_modified(version, "content_json")
        db.commit()
    detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
    groups = {}
    for row in _bullets(detail["content_json"]):
        groups.setdefault((row["section"], row["item_index"]), []).append(row)
    same_item = next(group for group in groups.values() if len(group) >= 2)
    first, second = same_item[0]["bullet"], same_item[1]["bullet"]
    moved = client.post(
        f"/api/resume-versions/{version_id}/reorder",
        json={"bullet_id": first["id"], "direction": "down"},
    )
    assert moved.status_code == 200, moved.text
    after_groups = {}
    for row in _bullets(moved.json()["content_json"]):
        after_groups.setdefault((row["section"], row["item_index"]), []).append(row)
    after = after_groups[same_item[0]["section"], same_item[0]["item_index"]]
    assert after[0]["bullet"]["id"] == second["id"]
    assert after[1]["bullet"]["id"] == first["id"]
    assert after[0]["bullet"]["text"] == second["text"]
    assert after[1]["bullet"]["text"] == first["text"]


def test_claim_token_is_atomic_and_interrupt_can_reclaim(client, db, monkeypatch):
    _user, resume, profile = setup_bundle(client, db)
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-claim"},
        json={"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
    )
    assert created.status_code == 202
    bundle_id = created.json()["id"]
    first = claim_bundle_run(db, bundle_id)
    second = claim_bundle_run(db, bundle_id)
    assert first
    assert second is None
    monkeypatch.setattr("app.services.bundle_service.CLAIM_STALE_AFTER", timedelta(seconds=0))
    run = db.get(ResumeBundleRun, bundle_id)
    run.updated_at = now() - timedelta(seconds=1)
    db.flush()
    processed = client.post(f"/api/resume-bundles/{bundle_id}/process")
    assert processed.status_code == 202, processed.text
    assert processed.json()["status"] in {"ready", "degraded"}
    assert "claim_token" not in processed.json()["run"]


def test_concurrent_workers_only_one_claims_a_queued_bundle(client, db):
    _user, resume, profile = setup_bundle(client, db)
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-concurrent-claim"},
        json={"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
    )
    assert created.status_code == 202
    bundle_id = created.json()["id"]
    db.commit()

    worker_engine = make_engine()
    WorkerSession = sessionmaker(bind=worker_engine, expire_on_commit=False)
    start = Barrier(2)

    def attempt_claim():
        with WorkerSession() as worker_db:
            start.wait()
            token = claim_bundle_run(worker_db, bundle_id)
            worker_db.commit()
            return token

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            tokens = list(pool.map(lambda _index: attempt_claim(), range(2)))
    finally:
        worker_engine.dispose()

    assert sum(token is not None for token in tokens) == 1
    db.expire_all()
    run = db.get(ResumeBundleRun, bundle_id)
    assert run.status == "generating"
    assert run.attempts == 1
    assert run.claim_token == next(token for token in tokens if token is not None)


def test_stale_worker_cannot_persist_after_claim_takeover(client, db):
    _user, resume, profile = setup_bundle(client, db)
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-stale-worker"},
        json={"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
    )
    assert created.status_code == 202
    bundle_id = created.json()["id"]
    first = claim_bundle_run(db, bundle_id)
    assert first
    run = db.get(ResumeBundleRun, bundle_id)
    run.updated_at = now() - timedelta(seconds=1)
    db.commit()
    second = claim_bundle_run(db, bundle_id, stale_after=timedelta(0))
    assert second and second != first
    stale_result = _apply_pair_result(db, bundle_id, first, {"status": "ready"})
    assert stale_result is not None
    assert stale_result.status == "generating"
    assert not list(db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == bundle_id)))


def test_content_change_stales_guides_and_allows_regenerate(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-guide-stale",
    )
    version_id = processed["versions"]["submittable"]["id"]
    before_hash = processed["versions"]["submittable"]["content_hash"]
    regenerated = client.post(
        f"/api/resume-versions/{version_id}/regenerate",
        json={"scope": "all"},
    )
    assert regenerated.status_code == 200, regenerated.text
    if regenerated.json()["content_hash"] == before_hash:
        version = db.get(ResumeVersion, version_id)
        content = version.content_json
        content["headline"] = f"{content.get('headline') or '简历'} · 修订"
        flag_modified(version, "content_json")
        db.flush()
        regenerated = client.post(
            f"/api/resume-versions/{version_id}/regenerate",
            json={"scope": "all"},
        )
    guides = list(db.scalars(select(InterviewGuide).where(InterviewGuide.bundle_id == processed["id"])))
    assert any(guide.status == "stale" for guide in guides)
    stale = next(guide for guide in guides if guide.status == "stale")
    refreshed = client.post(f"/api/interview-guides/{stale.id}/regenerate")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "ready"


def test_star_story_change_uses_new_fingerprint_and_stales_only_bound_target_guide(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, bundle = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-star-story-stale",
    )
    target_id = bundle["versions"]["target"]["id"]
    target = client.get(f"/api/resume-versions/{target_id}/studio").json()
    content = target["content_json"]
    story = next(
        item["project_story"]
        for section in content["sections"]
        for item in section.get("items") or []
        if item.get("project_story")
    )
    story["task"]["goal"] = f"{story['task']['goal']}，并补齐可复核的验收记录"
    changed = client.patch(f"/api/resume-versions/{target_id}", json=content)
    assert changed.status_code == 200, changed.text
    assert changed.json()["content_hash"] != target["content_hash"]
    target_guide = client.get(f"/api/interview-guides/{bundle['guides']['target']['id']}").json()
    submittable_guide = client.get(f"/api/interview-guides/{bundle['guides']['submittable']['id']}").json()
    assert target_guide["status"] == "stale"
    assert submittable_guide["status"] == "ready"
    refreshed = client.post(f"/api/interview-guides/{target_guide['id']}/regenerate")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "ready"


def test_fact_guard_overrides_high_critic_score():
    content = validate_content(
        {
            "content_version": 3,
            "kind": "submittable",
            "headline": "机械设计工程师",
            "contact": {},
            "sections": [
                {
                    "name": "项目/科研/竞赛",
                    "items": [
                        {
                            "organization": "实验室",
                            "role_title": "学生",
                            "bullets": [
                                {
                                    "text": "独立完成火星基地建设",
                                    "source_fact_ids": ["fact-1"],
                                    "source_target_ids": [],
                                    "requirement_ids": [],
                                    "achieved": True,
                                    "locked": False,
                                    "new_claims": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    fact = SimpleNamespace(
        id="fact-1",
        verification_status="user_confirmed",
        value_json={"text": "完成装配体建模"},
        source_text="完成装配体建模",
        organization="实验室",
        role_title="学生",
        start_date="",
        end_date="",
    )
    report = evaluate_version(
        content=content,
        facts=[fact],
        requirements=[],
        mode="submittable",
    )
    report = apply_critic_cannot_override(report, 99)
    assert report["status"] == "blocked"
    assert report["hard_passed"] is False
    assert report.get("reviewer") == "deterministic"


def test_studio_export_uses_snapshot_and_marks_blueprint(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, bundle = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-export",
    )
    target_id = bundle["versions"]["target"]["id"]
    html = client.get(f"/api/resume-versions/{target_id}/studio-preview")
    assert html.status_code == 200, html.text
    target = client.get(f"/api/resume-versions/{target_id}/studio").json()["content_json"]
    rendered = render_resume_html(target, "蓝图")
    docx = render_resume_docx(target, "蓝图").decode("latin-1", errors="ignore")
    if any(row["bullet"].get("achieved") is False for row in _bullets(target)):
        assert "*" in rendered
        assert BLUEPRINT_FOOTER in rendered
        assert rendered.count(BLUEPRINT_FOOTER) == 1
        assert BLUEPRINT_FOOTER in docx or "*" in docx
    sub_id = bundle["versions"]["submittable"]["id"]
    sub_html = client.get(f"/api/resume-versions/{sub_id}/studio-preview")
    assert sub_html.status_code == 200
    assert BLUEPRINT_FOOTER not in sub_html.text
    download = client.get(f"/api/resume-versions/{sub_id}/studio-download?format=docx")
    assert download.status_code == 200
    version = db.get(ResumeVersion, sub_id)
    version.template_snapshot_json = template_snapshot({"colors": {"accent": "ABCDEF"}})
    flag_modified(version, "template_snapshot_json")
    db.commit()
    snapshot_html = client.get(f"/api/resume-versions/{sub_id}/studio-preview")
    assert "ABCDEF" in snapshot_html.text
    snapshot_docx = client.get(f"/api/resume-versions/{sub_id}/studio-download?format=docx")
    with zipfile.ZipFile(io.BytesIO(snapshot_docx.content)) as archive:
        styles_xml = archive.read("word/styles.xml").decode("utf-8")
    assert "ABCDEF" in styles_xml
    pdf = client.get(f"/api/resume-versions/{sub_id}/studio-download?format=pdf")
    if converter_available():
        assert pdf.status_code == 200, pdf.text
        qa = inspect_pdf_bytes(pdf.content, version.content_json)
        assert qa["status"] == "passed", qa["issues"]
    else:
        assert pdf.status_code == 503
        assert pdf.json()["error"]["code"] == "PDF_CONVERTER_UNAVAILABLE"


def test_guides_cover_visible_bullets_and_omit_practice(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, bundle = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-guides",
    )
    assert bundle["guides"]
    sub_guide_id = bundle["guides"]["submittable"]["id"]
    guide = client.get(f"/api/interview-guides/{sub_guide_id}").json()
    assert guide["practice_enabled"] is False
    assert guide["scoring_enabled"] is False
    assert "answers" not in guide["content_json"]
    version = client.get(f"/api/resume-versions/{bundle['versions']['submittable']['id']}/studio").json()
    bullet_ids = [row["bullet"]["id"] for row in _bullets(version["content_json"])]
    card_ids = [card["bullet_id"] for card in guide["content_json"]["cards"]]
    assert set(card_ids) == set(bullet_ids)
    first_card = guide["content_json"]["cards"][0]
    assert profile["title"] in first_card["main_question"] or first_card.get("degraded")
    target_guide = client.get(f"/api/interview-guides/{bundle['guides']['target']['id']}").json()
    assert target_guide["content_json"].get("practice_answers") is False


def test_guide_model_omission_is_repaired_before_ready(client, db, monkeypatch):
    user = register(client, email="guide-coverage@example.test")
    _confirm_material(
        client,
        title="装配体课程设计",
        organization="用户自己的实验室",
        summary="使用 SolidWorks 完成装配体建模",
        extra="SolidWorks",
    )
    _confirm_material(
        client,
        title="PLC 点检练习",
        organization="用户自己的车间",
        summary="跟随师傅完成 PLC 点检并记录报警代码",
        extra="PLC",
    )
    _job, profile = _import_job(client)
    _grant_resume_quota(db, user["id"], key="resume-guide-coverage-grant")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        if _is_resume_copy_payload(payload):
            if payload.get("pair"):
                pair = _pair_rewrite_output(payload)
                for kind in ("submittable", "target"):
                    pair[kind]["sections"][0]["items"][0]["bullets"] = [
                        {
                            "text": fact["text"],
                            "source_fact_ids": [fact["id"]],
                            "source_target_ids": [],
                            "requirement_ids": [],
                            "achieved": True,
                            "new_claims": [],
                        }
                        for fact in payload.get("facts") or []
                    ]
                pair["target"]["sections"][0]["items"][0]["bullets"].extend(
                    {
                        "text": requirement["text"],
                        "source_fact_ids": [],
                        "source_target_ids": [requirement["id"]],
                        "requirement_ids": [requirement["id"]],
                        "achieved": False,
                        "new_claims": [],
                    }
                    for requirement in payload.get("requirements") or []
                    if requirement.get("id") and requirement.get("text")
                )
                return _structured_llm_response(pair)
            output = _rewrite_output_from_payload(payload)
            output["sections"][0]["items"][0]["bullets"] = [
                {
                    "text": fact["text"],
                    "source_fact_ids": [fact["id"]],
                    "source_target_ids": [],
                    "requirement_ids": [],
                    "achieved": True,
                    "new_claims": [],
                }
                for fact in payload.get("facts") or []
            ]
            if payload.get("kind") == "target":
                output["sections"][0]["items"][0]["bullets"].extend(
                    {
                        "text": requirement["text"],
                        "source_fact_ids": [],
                        "source_target_ids": [requirement["id"]],
                        "requirement_ids": [requirement["id"]],
                        "achieved": False,
                        "new_claims": [],
                    }
                    for requirement in payload.get("requirements") or []
                )
            return _structured_llm_response(output)
        if "hard_passed" in payload:
            return _structured_llm_response({"dimensions": {}, "summary": "ok"})
        if "bullets" in payload:
            bullets = payload.get("bullets") or []
            return _structured_llm_response(
                {
                    "kind": payload.get("kind") or "submittable",
                    "cards": ([{"bullet_id": bullets[0]["id"]}] if bullets else []),
                }
            )
        return _structured_llm_response({"kind": payload.get("kind") or "submittable", "cards": []})

    _install_compatible_provider(monkeypatch, handler)
    _created, processed = process_created_bundle(
        client,
        {"target_profile_id": profile["id"]},
        "bundle-guide-coverage",
    )
    guide = client.get(f"/api/interview-guides/{processed['guides']['submittable']['id']}").json()
    version = client.get(
        f"/api/resume-versions/{processed['versions']['submittable']['id']}/studio"
    ).json()
    expected = {row["bullet"]["id"] for row in _bullets(version["content_json"])}
    actual = {card["bullet_id"] for card in guide["content_json"]["cards"]}
    assert actual == expected
    assert guide["status"] == "ready"
    assert guide["quality_report_json"]["coverage"] == 1
    assert guide["quality_report_json"]["issues"] == ["coverage_repaired"]


def test_quality_report_omits_prompts_and_labels_reviewer(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, bundle = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-quality",
    )
    version = client.get(
        f"/api/resume-versions/{bundle['versions']['submittable']['id']}/studio"
    ).json()
    report = version["quality_report_json"]
    assert "dimensions" in report
    assert "prompt" not in report
    assert "model_prompt" not in str(report)
    assert report.get("reviewer") in {"model", "deterministic"}
    if report.get("reviewer") == "deterministic":
        assert "确定性" in (report.get("reviewer_note") or "")
    assert version["template_snapshot_json"]["id"] == "classic-navy-ats-v2"


def test_template_snapshot_is_stable_and_has_no_private_paths():
    snapshot = template_snapshot({"colors": {"accent": "000000"}})
    current = template_snapshot()
    assert snapshot["colors"]["accent"] == "000000"
    assert current["colors"]["accent"] != "000000"
    assert "resume_self" not in str(snapshot)
    assert "classic-navy-ats-v2" == current["id"]


def test_pdf_export_module_does_not_read_private_resume_dir():
    from app.services import pdf_export
    source = Path(pdf_export.__file__).read_text()
    assert "resume_self" not in source
    assert "resume_pdf/private" not in source
    assert '"embedded": "yes" if name' not in source
    assert "_font_rows_from_pdf_objects" in source


def test_education_section_follows_headline_order():
    content = {
        "content_version": 3,
        "kind": "submittable",
        "headline": "机械设计工程师",
        "contact": {"name": "测试用户"},
        "sections": [
            {
                "name": "教育背景",
                "items": [
                    {
                        "organization": "示例大学",
                        "role_title": "本科",
                        "bullets": [
                            {
                                "text": "机械工程本科",
                                "source_fact_ids": ["f1"],
                                "source_target_ids": [],
                                "requirement_ids": [],
                                "achieved": True,
                                "locked": False,
                                "new_claims": [],
                            }
                        ],
                    }
                ],
            },
            {
                "name": "项目/科研/竞赛",
                "items": [
                    {
                        "organization": "实验室",
                        "role_title": "学生",
                        "bullets": [
                            {
                                "text": "完成装配体",
                                "source_fact_ids": ["f2"],
                                "source_target_ids": [],
                                "requirement_ids": [],
                                "achieved": True,
                                "locked": False,
                                "new_claims": [],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    html = render_resume_html(content, "机械设计工程师")
    assert html.index("教育背景") < html.index("项目/科研/竞赛")
    assert html.index("意向") < html.index("教育背景") or "机械设计工程师" in html


def _critic_or_guide_response(payload: dict) -> httpx.Response | None:
    if "hard_passed" in payload:
        return _structured_llm_response({"dimensions": {}, "summary": "ok"})
    if "profile_title" in payload or "bullets" in payload:
        return _structured_llm_response(
            {
                "kind": payload.get("kind") or "submittable",
                "cards": [],
                "self_intro_60s": "用 60 秒说明求职方向。",
                "self_intro_90s": "用 90 秒补上教育背景。",
                "jd_questions": [],
                "motivation": "",
                "questions_to_ask": [],
                "checklist": [],
            }
        )
    return None


def test_unsourced_bullet_rewrite_calls_writer_and_changes_text(client, db, monkeypatch):
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        if payload.get("scope") == "bullet" or payload.get("current_bullet"):
            captured.append(payload)
            assert payload.get("current_bullet")
            assert "mock_response" not in payload
            return _structured_llm_response(
                {
                    "text": "面向装配体岗位重写的无来源要点，并写清个人承担的步骤",
                    "source_fact_ids": [],
                    "source_target_ids": [],
                    "requirement_ids": [],
                    "achieved": False,
                    "new_claims": ["无来源扩写"],
                    "verification_status": "ai_generated",
                }
            )
        other = _critic_or_guide_response(payload)
        if other is not None:
            return other
        orphan = {
            "id": "ai-orphan",
            "text": "AI 补充的无来源要点",
            "source_fact_ids": [],
            "source_target_ids": [],
            "requirement_ids": [],
            "achieved": False,
            "new_claims": ["无来源扩写"],
            "verification_status": "ai_generated",
        }
        if payload.get("pair"):
            pair = _pair_rewrite_output(payload)
            pair["submittable"]["sections"][0]["items"][0]["bullets"].append(orphan)
            return _structured_llm_response(pair)
        output = _rewrite_output_from_payload(payload)
        output["sections"][0]["items"][0]["bullets"].append(orphan)
        return _structured_llm_response(output)

    _install_compatible_provider(monkeypatch, handler)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-unsourced-rewrite",
    )
    version_id = processed["versions"]["submittable"]["id"]
    detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
    orphan = next(
        row["bullet"]
        for row in _bullets(detail["content_json"])
        if not row["bullet"].get("source_fact_ids") and not row["bullet"].get("requirement_ids")
    )
    original_text = orphan["text"]
    regenerated = client.post(
        f"/api/resume-versions/{version_id}/regenerate",
        json={"scope": "bullet", "bullet_id": orphan["id"]},
    )
    assert regenerated.status_code == 200, regenerated.text
    assert captured, "writer was not called for unsourced bullet"
    after = next(
        row["bullet"]
        for row in _bullets(regenerated.json()["content_json"])
        if row["bullet"]["id"] == orphan["id"]
    )
    assert after["text"] != original_text
    assert "重写的无来源要点" in after["text"]
    assert after.get("source_fact_ids") in ([], None)


def test_full_regen_keeps_model_expansion_instead_of_fallback_template(client, db, monkeypatch):
    first_text = "使用 Python 构建自动化分析流程"
    second_text = "使用 Python 构建可复核的自动化分析流程并缩短处理时间"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        other = _critic_or_guide_response(payload)
        if other is not None and "facts" not in payload:
            return other
        if _is_resume_copy_payload(payload):
            text = second_text if payload.get("current_content") or payload.get("current_submittable") else first_text
            extra = {
                "text": text,
                "source_fact_ids": [],
                "achieved": False,
                "new_claims": ["自动化分析流程"],
                "verification_status": "ai_generated",
            }
            if payload.get("pair"):
                pair = _pair_rewrite_output(payload)
                pair["submittable"]["sections"][0]["items"][0]["bullets"].append(extra)
                return _structured_llm_response(pair)
            output = _rewrite_output_from_payload(payload)
            output["sections"][0]["items"][0]["bullets"].append(extra)
            return _structured_llm_response(output)
        return _critic_or_guide_response(payload) or _structured_llm_response(
            {"kind": payload.get("kind") or "submittable", "cards": []}
        )

    _install_compatible_provider(monkeypatch, handler)
    _user, resume, profile = setup_bundle(client, db)
    _created, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-full-regen-writer",
    )
    version_id = processed["versions"]["submittable"]["id"]
    before = client.get(f"/api/resume-versions/{version_id}/studio").json()
    assert any(row["bullet"]["text"] == first_text for row in _bullets(before["content_json"]))
    regenerated = client.post(
        f"/api/resume-versions/{version_id}/regenerate",
        json={"scope": "all"},
    )
    assert regenerated.status_code == 200, regenerated.text
    texts = [row["bullet"]["text"] for row in _bullets(regenerated.json()["content_json"])]
    assert second_text in texts
    assert first_text not in texts


def test_generation_releases_write_lock_before_model_call(client, db, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        if _is_resume_copy_payload(payload) and "status" not in seen:
            engine = make_engine()
            Other = sessionmaker(bind=engine, expire_on_commit=False)
            with Other() as other:
                row = other.get(ResumeBundle, seen["bundle_id"])
                seen["status"] = row.status if row else None
                user = other.get(User, seen["user_id"])
                user.display_name = "concurrent-write"
                other.commit()
                seen["wrote"] = True
            engine.dispose()
            written = _resume_copy_response(payload)
            return written or _structured_llm_response(_rewrite_output_from_payload(payload))
        other = _critic_or_guide_response(payload)
        if other is not None:
            return other
        written = _resume_copy_response(payload)
        if written is not None:
            return written
        return _structured_llm_response({"kind": payload.get("kind") or "submittable", "cards": []})

    user, resume, profile = setup_bundle(client, db)
    created = client.post(
        "/api/resume-bundles",
        headers={"Idempotency-Key": "bundle-lock-release"},
        json={"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
    )
    assert created.status_code == 202, created.text
    seen["bundle_id"] = created.json()["id"]
    seen["user_id"] = user["id"]
    _install_compatible_provider(monkeypatch, handler)
    processed = client.post(f"/api/resume-bundles/{created.json()['id']}/process")
    assert processed.status_code == 202, processed.text
    assert seen.get("status") == "generating"
    assert seen.get("wrote") is True
    db.expire_all()
    assert db.get(User, user["id"]).display_name == "concurrent-write"


def test_pdf_qa_fails_when_fonts_cannot_be_verified(monkeypatch):
    from app.services import pdf_export

    real_which = shutil.which
    monkeypatch.setattr(
        pdf_export.shutil,
        "which",
        lambda name: None if name == "pdffonts" else real_which(name),
    )
    monkeypatch.setattr(pdf_export, "_font_rows_from_pdf_objects", lambda path: [])
    if not converter_available():
        return
    content = {
        "content_version": 3,
        "kind": "submittable",
        "headline": "机械设计工程师",
        "contact": {"name": "测试用户"},
        "sections": [
            {
                "name": "技能",
                "items": [
                    {
                        "bullets": [
                            {
                                "text": "SolidWorks",
                                "source_fact_ids": ["f1"],
                                "source_target_ids": [],
                                "requirement_ids": [],
                                "achieved": True,
                                "locked": False,
                                "new_claims": [],
                            }
                        ]
                    }
                ],
            }
        ],
    }
    try:
        asyncio.run(pdf_export.export_pdf(content, "机械设计工程师"))
        raise AssertionError("PDF QA should fail without verified fonts")
    except AppError as exc:
        assert exc.code == "PDF_QA_FAILED"
        issues = (exc.details or {}).get("issues") or []
        assert any("font" in str(item).lower() for item in issues)


def test_guide_download_includes_follow_ups_and_story(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _created, bundle = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-guide-download",
    )
    guide_id = bundle["guides"]["submittable"]["id"]
    page = client.get(f"/api/interview-guides/{guide_id}/download")
    assert page.status_code == 200, page.text
    assert "连续追问" in page.text
    assert "六段式讲法" in page.text
    assert "核验材料" in page.text
    assert "90 秒自我介绍" in page.text
