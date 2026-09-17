"""Fictional probes: same-source plans, guide isolation and honest boundaries."""

from copy import deepcopy
from types import SimpleNamespace

from app.services.content_contract import content_fingerprint
from app.services.copy_assembler import assemble_model_copy
from app.services.interview_guide_service import _project_cards_for_version

REQUIREMENTS = [{"id": "r-data", "text": "Python 数据清洗", "priority": "high"}]


def _story(project_id, title):
    return {
        "schema_version": 1,
        "project_id": project_id,
        "title": title,
        "situation": {"context": f"{title}的场景", "problem": f"{title}需要解决的问题"},
        "task": {"role": f"{title}负责人", "goal": f"交付{title}的可验证产物"},
        "actions": [{
            "step": f"执行{title}的第一步",
            "method": f"{title}专用方法",
            "rationale": "为了可复核",
            "difficulty": "边界条件不明确",
            "contribution": f"本人负责{title}的方案与记录",
        }],
        "result": {
            "deliverables": [f"{title}交付物"],
            "verification_method": "按验收清单逐项检查",
            "metrics": [],
        },
        "design_assumptions": [f"{title}假设使用公开数据集"],
        "open_questions": [f"{title}的样本规模尚未确定"],
        "bullet_ids": [f"b-{project_id}"],
        "source_fact_ids": [],
        "source_target_ids": ["r-data"],
        "requirement_ids": ["r-data"],
        "verification_status": "ai_generated",
        "achieved": False,
    }


def _content():
    return {
        "content_version": 3,
        "factuality_policy": "ai_expansion",
        "project_story_contract_version": 1,
        "kind": "target",
        "headline": "数据分析实习生",
        "sections": [{
            "name": "项目/科研/竞赛",
            "items": [
                {
                    "organization": "项目甲",
                    "bullets": [{"id": "b-alpha", "text": "完成项目甲的可验证产物",
                                 "achieved": False, "source_fact_ids": [], "new_claims": []}],
                    "project_story": _story("alpha", "项目甲"),
                },
                {
                    "organization": "项目乙",
                    "bullets": [{"id": "b-beta", "text": "完成项目乙的可验证产物",
                                 "achieved": False, "source_fact_ids": [], "new_claims": []}],
                    "project_story": _story("beta", "项目乙"),
                },
            ],
        }],
    }


def test_guide_project_cards_are_isolated_per_project():
    cards = _project_cards_for_version(SimpleNamespace(content_json=_content()))
    assert [card["project_id"] for card in cards] == ["alpha", "beta"]
    by_id = {card["project_id"]: card for card in cards}
    assert by_id["alpha"]["bullet_ids"] == ["b-alpha"]
    assert by_id["alpha"]["title"] == "项目甲"
    assert "项目甲专用方法" in str(by_id["alpha"]["star_outline"])
    assert "项目乙" not in str(by_id["alpha"])
    assert "项目甲" not in str(by_id["beta"])


def test_guide_lists_unverified_plan_assumptions_as_preparation_questions():
    card = _project_cards_for_version(SimpleNamespace(content_json=_content()))[0]
    assert card["achieved"] is False
    assert card["honest_boundary"]
    assert card["design_assumptions"] == ["项目甲假设使用公开数据集"]
    assert card["open_questions"] == ["项目甲的样本规模尚未确定"]
    joined = " ".join(card["preparation_questions"])
    assert "项目甲的样本规模尚未确定" in joined
    assert "项目甲假设使用公开数据集" in joined
    assert card["follow_up_chains"]
    assert "项目甲专用方法" in str(card["follow_up_chains"])


def test_plan_open_question_change_updates_fingerprint_and_stales_only_that_guide():
    content = _content()
    before = content_fingerprint(content)
    changed = deepcopy(content)
    changed["sections"][0]["items"][0]["project_story"]["open_questions"] = ["改为验证采样频率"]
    assert content_fingerprint(changed) != before
    # Re-saving the identical semantic content keeps the same fingerprint.
    assert content_fingerprint(deepcopy(content)) == before


def test_job_seeking_assembly_drops_blueprint_project_story():
    payload = {
        "headline": "数据分析实习生",
        "sections": [{
            "name": "项目/科研/竞赛",
            "items": [{
                "organization": "项目甲",
                "project_story": _story("alpha", "项目甲"),
                "bullets": [{
                    "text": "完成项目甲的可验证产物",
                    "requirement_ids": ["r-data"],
                    "source_target_ids": ["r-data"],
                    "achieved": False,
                }],
            }],
        }],
    }
    assembled = assemble_model_copy(
        payload,
        facts=[],
        requirements=REQUIREMENTS,
        kind="submittable",
        headline="数据分析实习生",
        contact={},
    )
    stories = [
        item.get("project_story")
        for section in assembled["sections"]
        for item in section.get("items") or []
    ]
    assert stories == [None]
    assert _project_cards_for_version(SimpleNamespace(content_json=assembled)) == []


def test_target_assembly_keeps_versioned_design_assumptions_and_open_questions():
    payload = {
        "headline": "数据分析实习生",
        "sections": [{
            "name": "项目/科研/竞赛",
            "items": [{
                "organization": "项目甲",
                "project_story": _story("alpha", "项目甲"),
                "bullets": [{
                    "text": "完成项目甲的可验证产物",
                    "requirement_ids": ["r-data"],
                    "source_target_ids": ["r-data"],
                    "achieved": False,
                }],
            }],
        }],
    }
    assembled = assemble_model_copy(
        payload,
        facts=[],
        requirements=REQUIREMENTS,
        kind="target",
        headline="数据分析实习生",
        contact={},
    )
    story = assembled["sections"][0]["items"][0]["project_story"]
    assert story["design_assumptions"] == ["项目甲假设使用公开数据集"]
    assert story["open_questions"] == ["项目甲的样本规模尚未确定"]
