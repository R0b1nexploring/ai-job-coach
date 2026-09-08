"""Expansion is deliverable, without promoting AI content into confirmed facts."""
import io
import json
from copy import deepcopy

import pytest
from docx import Document
from sqlalchemy import select

from app.models.entities import ResumeFact
from app.services.content_contract import validate_content, visible_bullets
from app.services.quality_service import evaluate_version
from conftest import register
from test_resume_generation_v3 import (
    _grant_resume_quota, _import_job, _install_compatible_provider,
    _pair_rewrite_output, _rewrite_output_from_payload, _structured_llm_response,
    process_created_bundle, setup_bundle,
)


def test_provider_expansion_survives_delivery_without_confirming_facts(client, db, monkeypatch):
    _, resume, profile = setup_bundle(client, db)
    before = {fact.id: fact.verification_status for fact in db.scalars(select(ResumeFact))}
    generated_text = "使用 Python 构建自动化分析流程，将处理时间缩短 30%"
    captured = []

    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        if "hard_passed" in payload:
            return _structured_llm_response({"dimensions": {}, "summary": "表达清楚"})
        if "bullets" in payload:
            return _structured_llm_response({"kind": payload["kind"], "cards": []})
        captured.append(payload)
        extra = {
            "text": generated_text,
            "source_fact_ids": [payload["facts"][0]["id"]] if payload.get("facts") else [],
            "achieved": True,
            "verification_status": "source_based",
            "new_claims": ["自动化分析流程", "处理时间缩短 30%"],
        }
        if payload.get("pair"):
            pair = _pair_rewrite_output(payload)
            pair["submittable"]["sections"][0]["items"][0]["bullets"].append(extra)
            pair["target"]["sections"][0]["items"][0]["bullets"].append(extra)
            return _structured_llm_response(pair)
        output = _rewrite_output_from_payload(payload)
        output["sections"][0]["items"][0]["bullets"].append(extra)
        if payload.get("kind") == "target":
            for requirement in payload.get("requirements") or []:
                output["sections"][0]["items"][0]["bullets"].append({
                    "text": requirement["text"], "achieved": False,
                    "requirement_ids": [requirement["id"]],
                })
        return _structured_llm_response(output)

    _install_compatible_provider(monkeypatch, handler)
    _, bundle = process_created_bundle(client, {
        "base_resume_id": resume["id"], "target_profile_id": profile["id"],
    }, "expansion-provider")
    assert bundle["status"] == "ready", bundle
    assert bundle["generation_metadata_json"]["writer"]["submittable"] == "model"
    assert captured[0]["facts"] and captured[0]["requirements"]
    for kind in ("submittable", "target"):
        version_id = bundle["versions"][kind]["id"]
        detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
        bullet = next(b for b in visible_bullets(detail["content_json"]) if b["text"] == generated_text)
        assert bullet["verification_status"] == "ai_generated"
        assert bullet["achieved"] is False
        assert bullet["new_claims"]
        assert detail["quality_report_json"]["hard_passed"] is True
        assert detail["quality_report_json"]["warnings"]
        html = client.get(f"/api/resume-versions/{version_id}/studio-preview")
        assert html.status_code == 200
        assert generated_text in html.text
        assert "待核验" not in html.text
        assert f"{generated_text}*" not in html.text
        docx = client.get(f"/api/resume-versions/{version_id}/studio-download?format=docx")
        assert docx.status_code == 200
        text = "\n".join(p.text for p in Document(io.BytesIO(docx.content)).paragraphs)
        assert generated_text in text
        assert "待核验" not in text
        guide = client.get(f"/api/interview-guides/{bundle['guides'][kind]['id']}").json()
        card = next(c for c in guide["content_json"]["cards"] if c["bullet_id"] == bullet["id"])
        assert card["achieved"] is False
        assert "待核验" not in card["honest_boundary"]
        assert "尚未核验" not in card["honest_boundary"]
    assert before == {fact.id: fact.verification_status for fact in db.scalars(select(ResumeFact))}


def test_jd_alone_can_generate_a_draft(client, db):
    user = register(client)
    _, profile = _import_job(client)
    _grant_resume_quota(db, user["id"])
    _, bundle = process_created_bundle(client, {"target_profile_id": profile["id"]}, "jd-only")
    assert bundle["status"] in {"ready", "degraded"}, bundle
    version_id = bundle["versions"]["submittable"]["id"]
    detail = client.get(f"/api/resume-versions/{version_id}/studio").json()
    bullets = visible_bullets(detail["content_json"])
    assert bullets and all(b["verification_status"] == "ai_generated" for b in bullets)
    assert client.get(f"/api/resume-versions/{version_id}/studio-preview").status_code == 200
    assert not list(db.scalars(select(ResumeFact)))


def expansion_content():
    return validate_content({
        "content_version": 3, "factuality_policy": "ai_expansion",
        "kind": "submittable", "headline": "数据分析",
        "sections": [{"name": "项目/科研/竞赛", "items": [{"bullets": [{
            "id": "draft-bullet", "text": "使用 Python 自动生成报告", "new_claims": ["自动生成报告"],
        }]}]}],
    })


@pytest.mark.parametrize("field", ["source_fact_ids", "source_target_ids", "requirement_ids"])
def test_expansion_does_not_allow_foreign_source_ids(field):
    content = expansion_content()
    visible_bullets(content)[0][field] = ["another-users-source"]
    report = evaluate_version(content=content, facts=[], requirements=[], mode="submittable")
    assert not report["hard_passed"]
    assert "引用了不属于当前生成上下文的来源" in report["issues"]


def test_expansion_keeps_layout_gate_and_legacy_fact_gate():
    content = expansion_content()
    assert evaluate_version(content=content, facts=[], requirements=[], mode="submittable")["hard_passed"]
    legacy = deepcopy(content)
    legacy.pop("factuality_policy")
    assert not evaluate_version(content=legacy, facts=[], requirements=[], mode="submittable")["hard_passed"]
    item = content["sections"][0]["items"][0]
    item["bullets"] = [{**deepcopy(item["bullets"][0]), "id": f"long-{i}"} for i in range(100)]
    report = evaluate_version(content=content, facts=[], requirements=[], mode="submittable")
    assert report["hard_passed"]
    assert "超过单页内容预算" in report["layout_warnings"]
    assert "超过单页内容预算" not in report["issues"]
