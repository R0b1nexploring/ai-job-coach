import asyncio
import io
import json
import shutil
import zipfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
from conftest import docx_file, register
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.config import Settings
from app.database import make_engine
from app.errors import AppError
from app.models.entities import InterviewGuide, ResumeBundle, ResumeBundleRun, ResumeVersion, User, now
from app.providers.llm.base import ProviderError
from app.providers.llm.compatible import CompatibleLLMProvider
from app.providers.llm.runtime import generate_structured as real_generate_structured
from app.services.bundle_service import claim_bundle_run
from app.services.content_contract import normalize_bullet, validate_content
from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html
from app.services.pdf_export import converter_available, inspect_pdf_bytes
from app.services.quality_service import apply_critic_cannot_override, evaluate_version
from app.services.quota_service import change
from app.services.resume_style import AI_EXPANSION_FOOTER, BLUEPRINT_FOOTER
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
    tgt_future = [row["bullet"] for row in _bullets(tgt.content_json) if row["bullet"].get("achieved") is False]
    assert all(row["bullet"].get("achieved") is not False for row in _bullets(sub.content_json))
    if tgt_future:
        assert all(bullet.get("requirement_ids") for bullet in tgt_future)
        assert all(bullet["text"] not in sub_texts for bullet in tgt_future)


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
        if payload.get("kind") in {"submittable", "target"} and "facts" in payload:
            return _structured_llm_response(_rewrite_output_from_payload(payload))
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
    rewrite_payloads = [
        item
        for item in captured
        if item.get("kind") in {"submittable", "target"} and "facts" in item
    ]
    assert rewrite_payloads, captured
    assert processed["status"] in {"ready", "degraded"}
    assert processed["generation_metadata_json"]["writer"]["submittable"] == "model"
    for payload in rewrite_payloads:
        assert "mock_response" not in payload
        assert payload != {}
        assert payload["facts"], payload
        assert any(item.get("text") for item in payload["facts"])
        assert payload["requirements"]
        assert any(item.get("text") for item in payload["requirements"])
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
    assert processed.json()["run"]["claim_token"] != first


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
        assert AI_EXPANSION_FOOTER in rendered
        assert rendered.count(AI_EXPANSION_FOOTER) == 1
        assert AI_EXPANSION_FOOTER in docx or "*" in docx
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
        output = _rewrite_output_from_payload(payload)
        output["sections"][0]["items"][0]["bullets"].append(
            {
                "id": "ai-orphan",
                "text": "AI 补充的无来源要点",
                "source_fact_ids": [],
                "source_target_ids": [],
                "requirement_ids": [],
                "achieved": False,
                "new_claims": ["无来源扩写"],
                "verification_status": "ai_generated",
            }
        )
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
        if payload.get("kind") in {"submittable", "target"} and "facts" in payload:
            output = _rewrite_output_from_payload(payload)
            text = second_text if payload.get("current_content") else first_text
            output["sections"][0]["items"][0]["bullets"].append(
                {
                    "text": text,
                    "source_fact_ids": [],
                    "achieved": False,
                    "new_claims": ["自动化分析流程"],
                    "verification_status": "ai_generated",
                }
            )
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
        if payload.get("kind") in {"submittable", "target"} and "facts" in payload and "status" not in seen:
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
            return _structured_llm_response(_rewrite_output_from_payload(payload))
        other = _critic_or_guide_response(payload)
        if other is not None:
            return other
        if payload.get("kind") in {"submittable", "target"} and "facts" in payload:
            return _structured_llm_response(_rewrite_output_from_payload(payload))
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
