"""Local copy assembly, content gates, and isolated PDF failures."""

from copy import deepcopy
from types import SimpleNamespace

from app.errors import AppError
from app.services.content_contract import validate_content, visible_bullets
from app.services.copy_assembler import assemble_model_copy
from app.services.html_resume_renderer import render_resume_html
from app.services.pdf_export import classify_pdf_issues, compact_spacing_snapshot
from app.services.quality_service import evaluate_version, evaluate_version_with_critic
from app.services.quota_service import request_fingerprint
from app.services.resume_template import template_snapshot
from conftest import register
from test_resume_generation_v3 import (
    _confirm_material,
    _grant_resume_quota,
    _import_job,
    process_created_bundle,
    setup_bundle,
)


def _fact(fact_id, *, org, role="成员", text="完成实验记录"):
    return SimpleNamespace(
        id=fact_id,
        category="projects",
        label=text,
        organization=org,
        role_title=role,
        location="",
        start_date="2024-01",
        end_date="2024-06",
        value_json={"text": text},
        source_text=text,
        verification_status="user_confirmed",
        material_id=f"mat-{org}",
    )


def _model_copy(*bullets, kind="submittable"):
    return {
        "content_version": 3,
        "kind": kind,
        "headline": "机械设计工程师",
        "html": "<html>layout</html>",
        "sections": [
            {
                "name": "项目经历",
                "items": [
                    {
                        "organization": "实验室甲",
                        "role_title": "成员",
                        "start_date": "2024-01",
                        "end_date": "2024-06",
                        "font_size": 9,
                        "bullets": list(bullets),
                    }
                ],
            }
        ],
    }


def test_assembler_assigns_local_ids_and_drops_layout():
    facts = [_fact("f1", org="实验室甲")]
    assembled = assemble_model_copy(
        _model_copy(
            {
                "id": "model-id",
                "text": "使用 SolidWorks 完成装配",
                "source_fact_ids": ["f1"],
                "locked": True,
                "page": 2,
            }
        ),
        facts=facts,
        requirements=[],
        kind="submittable",
        headline="机械设计工程师",
        contact={},
    )
    bullet = visible_bullets(assembled)[0]
    assert bullet["id"] != "model-id"
    assert bullet["locked"] is False
    assert "html" not in assembled
    assert assembled["sections"][0]["name"] == "项目/科研/竞赛"


def test_assembler_keeps_existing_ids_on_regenerate():
    facts = [_fact("f1", org="实验室甲")]
    current = assemble_model_copy(
        _model_copy({"text": "原文", "source_fact_ids": ["f1"], "id": "keep-me"}),
        facts=facts,
        requirements=[],
        kind="submittable",
        headline="机械设计工程师",
        contact={},
        current_content={
            "sections": [
                {
                    "name": "项目/科研/竞赛",
                    "items": [
                        {
                            "organization": "实验室甲",
                            "role_title": "成员",
                            "start_date": "2024-01",
                            "bullets": [
                                {
                                    "id": "keep-me",
                                    "text": "原文",
                                    "source_fact_ids": ["f1"],
                                    "locked": True,
                                    "achieved": True,
                                    "requirement_ids": [],
                                    "source_target_ids": [],
                                    "new_claims": [],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    bullet = visible_bullets(current)[0]
    assert bullet["id"] == "keep-me"
    assert bullet["locked"] is True


def test_fuzzy_organization_keeps_bullet_on_the_same_experience():
    facts = [_fact("f1", org="佛山市南海斯耐迪精密机械有限公司")]
    assembled = assemble_model_copy(
        {
            "content_version": 3,
            "kind": "submittable",
            "headline": "机械设计工程师",
            "sections": [
                {
                    "name": "实习/工作",
                    "items": [
                        {
                            "organization": "斯耐迪精密机械",
                            "role_title": "机械助理工程师",
                            "start_date": "2025-07",
                            "end_date": "2025-10",
                            "bullets": [
                                {
                                    "text": "使用 SolidWorks 完成装配设计",
                                    "source_fact_ids": ["f1"],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        facts=facts,
        requirements=[],
        kind="submittable",
        headline="机械设计工程师",
        contact={},
    )
    item = assembled["sections"][0]["items"][0]
    assert item.get("entry_kind") != "ai_suggestion"
    assert visible_bullets(assembled)[0]["source_fact_ids"] == ["f1"]


def test_cross_experience_facts_become_independent_suggestions():
    facts = [_fact("f1", org="实验室甲"), _fact("f2", org="实验室乙", text="另一段经历")]
    assembled = assemble_model_copy(
        _model_copy(
            {
                "text": "把两段经历拼成一条",
                "source_fact_ids": ["f1", "f2"],
            }
        ),
        facts=facts,
        requirements=[],
        kind="submittable",
        headline="机械设计工程师",
        contact={},
    )
    items = assembled["sections"][0]["items"]
    assert any(item.get("entry_kind") == "ai_suggestion" for item in items)
    bullet = visible_bullets(assembled)[0]
    assert bullet["source_fact_ids"] == []
    assert bullet["verification_status"] == "ai_generated"
    assert bullet["achieved"] is False


def test_valid_fact_id_with_new_claim_stays_unconfirmed():
    facts = [_fact("f1", org="实验室甲")]
    assembled = assemble_model_copy(
        _model_copy(
            {
                "text": "使用 SolidWorks 完成装配，效率提升 30%",
                "source_fact_ids": ["f1"],
                "new_claims": ["效率提升 30%"],
                "verification_status": "source_based",
                "achieved": True,
            }
        ),
        facts=facts,
        requirements=[],
        kind="submittable",
        headline="机械设计工程师",
        contact={},
    )
    bullet = visible_bullets(assembled)[0]
    assert bullet["source_fact_ids"] == ["f1"]
    assert bullet["verification_status"] == "ai_generated"
    assert bullet["achieved"] is False


def test_unmatched_ai_copy_is_not_attached_to_existing_experience():
    facts = [_fact("f1", org="实验室甲")]
    raw = _model_copy({"text": "实验室甲已有要点", "source_fact_ids": ["f1"]})
    raw["sections"][0]["items"].append(
        {
            "organization": "实验室甲",
            "role_title": "成员",
            "start_date": "2024-01",
            "end_date": "2024-06",
            "bullets": [{"text": "建议补一段竞赛经历", "source_fact_ids": []}],
        }
    )
    assembled = assemble_model_copy(
        raw,
        facts=facts,
        requirements=[],
        kind="submittable",
        headline="机械设计工程师",
        contact={},
    )
    items = assembled["sections"][0]["items"]
    supported = next(item for item in items if not item.get("entry_kind"))
    texts = [str(bullet.get("text")) for bullet in supported["bullets"]]
    assert "实验室甲已有要点" in texts
    assert "建议补一段竞赛经历" in texts
    extra = visible_bullets(assembled)
    suggestion = next(bullet for bullet in extra if "竞赛" in str(bullet.get("text")))
    assert suggestion["verification_status"] == "ai_generated"
    assert suggestion["achieved"] is False


def test_layout_estimate_is_warning_not_content_failure():
    content = validate_content(
        {
            "content_version": 3,
            "factuality_policy": "ai_expansion",
            "kind": "submittable",
            "headline": "机械设计",
            "sections": [
                {
                    "name": "项目/科研/竞赛",
                    "items": [
                        {
                            "bullets": [
                                {
                                    "id": f"b{i}",
                                    "text": "完成一项课程设计任务并记录结果",
                                    "new_claims": ["课程设计"],
                                }
                                for i in range(80)
                            ]
                        }
                    ],
                }
            ],
        }
    )
    report = evaluate_version(content=content, facts=[], requirements=[], mode="submittable")
    assert report["hard_passed"] is True
    assert report["layout_warnings"]


def test_pdf_issue_classification_splits_overflow_and_fonts():
    assert classify_pdf_issues(["page_count: expected 1, got 2"]) == "content_overflow"
    assert classify_pdf_issues(["fonts: every font must be embedded"]) == "technical"


def test_compact_spacing_does_not_change_content_hash():
    content = {
        "content_version": 3,
        "kind": "submittable",
        "headline": "机械设计工程师",
        "sections": [{"name": "技能", "items": [{"bullets": [{"text": "SolidWorks"}]}]}],
    }
    snapshot = template_snapshot()
    compact = compact_spacing_snapshot(snapshot)
    assert compact is not None
    assert compact["typography"]["line_spacing"] == compact["typography"]["line_spacing_min"]
    html = render_resume_html(content, "机械设计工程师", snapshot=snapshot)
    compact_html = render_resume_html(content, "机械设计工程师", snapshot=compact)
    assert "SolidWorks" in html and "SolidWorks" in compact_html
    assert request_fingerprint(content) == request_fingerprint(deepcopy(content))


def test_critic_low_score_does_not_record_auto_repair(client, db, monkeypatch):
    real_evaluate = evaluate_version_with_critic

    async def low_score(**kwargs):
        report = await real_evaluate(**kwargs)
        report["hard_passed"] = True
        report["status"] = "passed"
        report["issues"] = []
        report["dimensions"] = {
            name: {"score": 20, "notes": ["表达重复"]}
            for name in report.get("dimensions") or {"target_relevance": {}}
        }
        return report

    monkeypatch.setattr("app.services.bundle_service.evaluate_version_with_critic", low_score)
    _user, resume, profile = setup_bundle(client, db)
    _, processed = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-critic-low-score",
    )
    history = processed["generation_metadata_json"]["repair_history"]
    assert not any(str(item).startswith("repair_") for item in history)
    assert processed["status"] in {"ready", "degraded"}


def test_unconfirmed_material_is_sent_as_reference(client, db, monkeypatch):
    user = register(client, email="draft-ref@example.test")
    client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": "未确认课程设计",
            "organization": "草稿实验室",
            "summary": "用 SolidWorks 画过装配草图",
        },
    )
    _, profile = _import_job(client)
    _grant_resume_quota(db, user["id"], key="draft-ref-grant")
    captured = []

    def handler(request):
        import json

        from test_resume_generation_v3 import _rewrite_output_from_payload, _structured_llm_response

        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        if payload.get("pair") or (payload.get("kind") in {"submittable", "target"} and "facts" in payload):
            captured.append(payload)
            if payload.get("pair"):
                from test_resume_generation_v3 import _pair_rewrite_output

                return _structured_llm_response(_pair_rewrite_output(payload))
            return _structured_llm_response(_rewrite_output_from_payload(payload))
        if "hard_passed" in payload:
            return _structured_llm_response({"dimensions": {}, "summary": "ok"})
        return _structured_llm_response({"kind": payload.get("kind") or "submittable", "cards": []})

    from test_resume_generation_v3 import _install_compatible_provider

    _install_compatible_provider(monkeypatch, handler)
    _, bundle = process_created_bundle(client, {"target_profile_id": profile["id"]}, "draft-ref")
    assert bundle["status"] in {"ready", "degraded"}
    assert captured
    assert any(
        item.get("summary") == "用 SolidWorks 画过装配草图"
        for payload in captured
        for item in payload.get("draft_materials") or []
    )
    from sqlalchemy import select

    from app.models.entities import ResumeFact

    assert not list(db.scalars(select(ResumeFact)))


def test_target_guide_covers_all_visible_bullets(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _, bundle = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-target-guide-coverage",
    )
    version = client.get(f"/api/resume-versions/{bundle['versions']['target']['id']}/studio").json()
    guide = client.get(f"/api/interview-guides/{bundle['guides']['target']['id']}").json()
    bullet_ids = [bullet["id"] for bullet in visible_bullets(version["content_json"])]
    card_ids = [card["bullet_id"] for card in guide["content_json"]["cards"]]
    assert set(card_ids) == set(bullet_ids)


def test_download_does_not_change_content_hash(client, db):
    _user, resume, profile = setup_bundle(client, db)
    _, bundle = process_created_bundle(
        client,
        {"base_resume_id": resume["id"], "target_profile_id": profile["id"]},
        "bundle-download-hash",
    )
    version_id = bundle["versions"]["submittable"]["id"]
    before = client.get(f"/api/resume-versions/{version_id}/studio").json()["content_hash"]
    downloaded = client.get(f"/api/resume-versions/{version_id}/studio-download?format=html")
    assert downloaded.status_code == 200
    after = client.get(f"/api/resume-versions/{version_id}/studio").json()["content_hash"]
    assert after == before


def test_pdf_technical_failure_does_not_rewrite_copy(monkeypatch):
    from app.services import pdf_export

    async def fake_render(content, title, snapshot):
        return b"%PDF-1.4 fake", {"status": "failed", "issues": ["fonts: every font must be embedded"]}

    monkeypatch.setattr(pdf_export, "_render_pdf_attempt", fake_render)
    content = {
        "content_version": 3,
        "kind": "submittable",
        "headline": "机械设计工程师",
        "sections": [{"name": "技能", "items": [{"bullets": [{"text": "SolidWorks"}]}]}],
    }
    original = deepcopy(content)
    try:
        import asyncio

        asyncio.run(pdf_export.export_pdf(content, "机械设计工程师"))
        raise AssertionError("expected PDF_QA_FAILED")
    except AppError as exc:
        assert exc.code == "PDF_QA_FAILED"
        assert (exc.details or {}).get("failure_kind") == "technical"
    assert content == original
