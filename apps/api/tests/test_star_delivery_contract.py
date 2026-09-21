"""STAR delivery contract: hard failures, targeted repair, and no-progress exit.

Task 17.3 makes known placeholder content a hard failure instead of an advisory
diagnostic. Task 17.4 routes concrete, located semantic errors into a scoped
background repair and keeps a previously found error open until a re-check on
the revised content clears it. All inputs here are fictional.
"""

import asyncio
from copy import deepcopy

import pytest

from app.providers.llm.schemas import QualityCriticOutput
from app.services.bundle_service import (
    _enforce_semantic_resolution,
    _semantic_repair_instruction,
)
from app.services.content_contract import iter_project_stories
from app.services.copy_assembler import assemble_model_copy
from app.services.quality_service import (
    CRITIC_COMPLETE,
    CRITIC_PARTIAL,
    CRITIC_UNAVAILABLE,
    QUALITY_DIMENSIONS,
    evaluate_version,
    evaluate_version_with_critic,
)

REQUIREMENTS = [{"id": "r-cad", "text": "能用 SolidWorks 输出装配体", "priority": "high"}]


def _concrete_story() -> dict:
    """A concrete STAR story with a verifiable, non-numeric deliverable."""
    return {
        "situation": {
            "context": "课程要求把零件装配流程整理成可复用的作业指导",
            "problem": "现有装配步骤散落在个人笔记中，无法交接给同学复现",
        },
        "task": {
            "role": "负责装配流程整理、建立装配层级并输出工程图",
            "goal": "产出一份可交接的装配作业指导与配套工程图",
        },
        "actions": [
            {
                "step": "把分散的装配步骤按装配顺序整理成标准作业清单",
                "method": "用 SolidWorks 装配体建立零件层级并导出爆炸图",
                "contribution": "负责整理步骤、建立装配层级并输出工程图",
                "rationale": "按装配顺序组织可以让同学按图复现",
                "difficulty": "部分零件缺少配合基准，需要额外定义定位方式",
            }
        ],
        "result": {
            "deliverables": ["装配作业指导、装配体模型与工程图"],
            "verification_method": "由同学按作业指导独立完成一次装配并记录卡点",
            "metrics": [
                {
                    "name": "交接卡点数",
                    "value": "目标为个位数",
                    "kind": "target",
                    "conditions": "由未参与整理的同学按作业指导复现并逐项记录",
                }
            ],
        },
    }


def _content(*, story_overrides=None):
    assembled = assemble_model_copy(
        {
            "sections": [
                {
                    "name": "项目经历",
                    "items": [
                        {
                            "organization": "虚构机械课程项目",
                            "bullets": [
                                {
                                    "text": "完成装配方案、工程图与验收记录",
                                    "requirement_ids": ["r-cad"],
                                    "source_target_ids": ["r-cad"],
                                    "achieved": False,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        facts=[],
        requirements=REQUIREMENTS,
        kind="target",
        headline="机械设计工程师",
        contact={},
    )
    story = next(iter_project_stories(assembled))[2]
    story.update(_concrete_story())
    if story_overrides:
        story.update(story_overrides)
    return assembled


def _review(content):
    return evaluate_version(
        content=content, facts=[], requirements=REQUIREMENTS, mode="target"
    )


def _critic(dimensions=None, *, project_id, bullet_ids, issue_code=""):
    return QualityCriticOutput.model_validate(
        {
            "dimensions": dimensions
            if dimensions is not None
            else {name: {"score": 90, "notes": []} for name in QUALITY_DIMENSIONS},
            "summary": "评审结论",
            "recommendations": [],
            "project_reviews": [
                {
                    "project_id": project_id,
                    "bullet_ids": bullet_ids,
                    "issue_code": issue_code,
                    "diagnosis": "装配步骤只覆盖了建模，未说明如何验证结果可复现",
                    "suggestions": ["补充复现验证记录"],
                }
            ],
        }
    )


def test_concrete_non_numeric_project_passes_the_delivery_contract():
    """No numeric result is required; a verifiable deliverable is enough."""
    content = _content()
    report = _review(content)
    assert report["hard_passed"] is True, report["issues"]
    story = next(iter_project_stories(content))[2]
    assert story["achieved"] is False
    assert all(metric["kind"] == "target" for metric in story["result"]["metrics"])


@pytest.mark.parametrize(
    ("field", "placeholder"),
    [
        ("situation", {"context": "业务需要"}),
        ("task", {"goal": "效果良好"}),
        ("actions", [{"step": "负责开发", "method": "使用工具"}]),
        ("result", {"deliverables": ["可演示的项目产出"]}),
    ],
)
def test_known_placeholders_are_hard_failures(field, placeholder):
    content = _content()
    story = next(iter_project_stories(content))[2]
    story[field] = placeholder
    report = _review(content)
    assert report["hard_passed"] is False
    assert report["status"] == "blocked"


def test_short_role_label_is_not_accepted_as_a_project_role():
    content = _content()
    story = next(iter_project_stories(content))[2]
    story["task"] = {"role": "成员", "goal": "交付装配体"}
    report = _review(content)
    assert report["hard_passed"] is False
    assert any("T（角色/目标）" in issue for issue in report["issues"])


def test_removing_the_project_does_not_bypass_the_check():
    """The contract must not be satisfiable by deleting the failing project."""
    content = _content()
    story = next(iter_project_stories(content))[2]
    story["situation"] = {"context": "业务需要", "problem": "效果不好"}
    assert _review(content)["hard_passed"] is False

    without = deepcopy(content)
    without["sections"] = [
        section
        for section in without["sections"]
        if not any("project_story" in item for item in section.get("items") or [])
    ]
    report = _review(without)
    # Dropping the only project leaves nothing to deliver, so it is still not a
    # pass; the check cannot be satisfied by omission.
    assert report["hard_passed"] is False


def test_semantic_issue_is_turned_into_a_scoped_repair_instruction():
    content = _content()
    story = next(iter_project_stories(content))[2]
    instruction = _semantic_repair_instruction(
        {
            "code": "action_result_mismatch",
            "project_id": story["project_id"],
            "bullet_ids": story["bullet_ids"],
            "diagnosis": "行动只描述建模，结果却声称完成生产优化",
        }
    )
    assert "action_result_mismatch" in instruction
    assert story["project_id"] in instruction
    assert story["bullet_ids"][0] in instruction
    # The repair is scoped and must not resolve the problem by deletion.
    assert "保留其他内容" in instruction
    assert "不要删除该项目" in instruction


def _semantic_issue(code="action_result_mismatch"):
    return {
        "code": code,
        "project_id": "p1",
        "bullet_ids": ["b1"],
        "diagnosis": "行动无法支撑结果",
    }


def test_unresolved_semantic_issue_survives_a_later_unavailable_review():
    """An earlier contradiction is not cleared by a later failed review."""
    history: list[str] = []
    _sub, _tgt, sub_open, tgt_open = _enforce_semantic_resolution(
        sub_report={"semantic_issues": [], "critic_status": CRITIC_COMPLETE},
        tgt_report={
            "semantic_issues": [_semantic_issue()],
            "critic_status": CRITIC_UNAVAILABLE,
        },
        repair_history=history,
    )
    assert (sub_open, tgt_open) == (False, True)
    assert "semantic_unresolved_target:review_incomplete" in history


def test_unresolved_semantic_issue_survives_a_high_later_score():
    """A high score never clears a still-reported semantic error."""
    history: list[str] = []
    _sub, _tgt, sub_open, tgt_open = _enforce_semantic_resolution(
        sub_report={"semantic_issues": [], "critic_status": CRITIC_COMPLETE},
        tgt_report={
            "semantic_issues": [_semantic_issue("plan_contradiction")],
            "critic_status": CRITIC_COMPLETE,
        },
        repair_history=history,
    )
    assert (sub_open, tgt_open) == (False, True)
    assert "semantic_unresolved_target:plan_contradiction" in history


def test_cleared_semantic_issue_lets_the_copy_proceed():
    history: list[str] = []
    _sub, _tgt, sub_open, tgt_open = _enforce_semantic_resolution(
        sub_report={"semantic_issues": [], "critic_status": CRITIC_COMPLETE},
        tgt_report={"semantic_issues": [], "critic_status": CRITIC_COMPLETE},
        repair_history=history,
    )
    assert (sub_open, tgt_open) == (False, False)
    assert history == []


def test_low_score_without_a_located_issue_does_not_trigger_repair(monkeypatch):
    """A low score alone stays explanatory and must not force a rewrite."""
    content = _content()
    story = next(iter_project_stories(content))[2]
    before = deepcopy(content)

    async def fake_generate_structured(**_kwargs):
        return (
            _critic(
                {"specificity": {"score": 20, "notes": ["表达偏笼统"]}},
                project_id=story["project_id"],
                bullet_ids=story["bullet_ids"],
                issue_code="",
            ),
            "compatible",
        )

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["critic_status"] == CRITIC_PARTIAL
    assert report["semantic_issues"] == []
    assert content == before


def test_located_semantic_issue_is_reported_for_repair(monkeypatch):
    content = _content()
    story = next(iter_project_stories(content))[2]

    async def fake_generate_structured(**_kwargs):
        return (
            _critic(
                project_id=story["project_id"],
                bullet_ids=story["bullet_ids"],
                issue_code="action_result_mismatch",
            ),
            "compatible",
        )

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["critic_status"] == CRITIC_COMPLETE
    assert [issue["code"] for issue in report["semantic_issues"]] == [
        "action_result_mismatch"
    ]
