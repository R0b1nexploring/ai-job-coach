"""Fictional project probes: detail preservation and actionable diagnostics."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

from app.providers.llm.schemas import QualityCriticOutput
from app.services.bundle_service import build_project_story_inputs
from app.services.content_contract import iter_project_stories
from app.services.copy_assembler import assemble_model_copy
from app.services.quality_service import (
    QUALITY_DIMENSIONS,
    CRITIC_COMPLETE,
    CRITIC_PARTIAL,
    CRITIC_UNAVAILABLE,
    evaluate_version,
    evaluate_version_with_critic,
)


REQUIREMENTS = [{"id": "r-data", "text": "Python 数据清洗", "priority": "high"}]


def _content():
    return assemble_model_copy(
        {
            "sections": [{"name": "项目经历", "items": [{
                "organization": "虚构课程项目",
                "bullets": [{
                    "text": "清理课程传感器采样表中的重复时间戳，编写去重脚本并输出异常记录与校验报告",
                    "requirement_ids": ["r-data"],
                    "source_target_ids": ["r-data"],
                    "achieved": False,
                }],
            }]}],
        },
        facts=[], requirements=REQUIREMENTS, kind="target",
        headline="数据分析实习生", contact={},
    )


def _review(content):
    return evaluate_version(content=content, facts=[], requirements=REQUIREMENTS, mode="target")


def _concrete_story(content):
    story = next(iter_project_stories(content))[2]
    story.update({
        "situation": {"context": "课程传感器采样表存在重复时间戳", "problem": "重复记录影响每日温度汇总"},
        "task": {"role": "清洗脚本负责人", "goal": "生成可重复执行的去重脚本和异常记录表"},
        "actions": [{
            "step": "按设备编号与采样时间标记重复记录",
            "method": "使用 Python 对复合键分组并输出冲突明细",
            "contribution": "计划编写去重逻辑和冲突记录导出",
            "rationale": "保留冲突明细以便核对，避免直接删除不同读数",
            "difficulty": "同一时间戳可能有不同温度值，需要单独记录冲突",
        }],
        "result": {
            "deliverables": ["去重脚本、冲突记录表和测试报告"],
            "verification_method": "构造重复键和冲突读数，逐项比较输出与预期记录",
            "metrics": [{"name": "重复键残留", "value": "目标为零", "kind": "target",
                         "conditions": "对包含重复键、空值与冲突读数的合成测试表执行检查"}],
        },
    })
    return story


def test_story_inputs_keep_each_projects_evidence_and_draft_details_isolated():
    facts = [SimpleNamespace(
        id="f-sensor", material_id="m-sensor", category="projects", label="传感器清洗",
        organization="虚构课程甲", role_title="脚本负责人",
        value_json={"text": "使用 Python 按设备与时间去重"}, source_text="合成数据课程练习",
        claim_type="action", evidence_json={"artifact": "去重测试记录"},
        verification_status="user_confirmed",
    )]
    drafts = [{"id": "m-other", "kind": "project", "title": "虚构装配练习",
               "summary": "设计定位销装配方案", "details": {"difficulty": "定位销配合公差尚未确定"}}]
    original = deepcopy(drafts)
    rows = build_project_story_inputs(facts, drafts, REQUIREMENTS, [])
    confirmed = next(row for row in rows if row["source"] == "confirmed_fact")
    draft = next(row for row in rows if row["source"] == "draft_material")
    assert [fact["id"] for fact in confirmed["facts"]] == ["f-sensor"]
    assert confirmed["facts"][0]["text"] == "使用 Python 按设备与时间去重"
    assert confirmed["facts"][0]["evidence_json"] == {"artifact": "去重测试记录"}
    assert "定位销" not in str(confirmed)
    assert draft["facts"] == []
    assert draft["material_summary"] == "设计定位销装配方案"
    assert draft["material_details"] == original[0]["details"]
    draft["material_details"]["difficulty"] = "改动输出副本"
    confirmed["facts"][0]["evidence_json"]["artifact"] = "改动输出副本"
    assert drafts == original
    assert facts[0].evidence_json == {"artifact": "去重测试记录"}


def test_project_plan_inputs_carry_source_specific_design_boundaries():
    facts = [SimpleNamespace(
        id="f-cad", material_id="m-cad", category="projects", label="装配练习",
        organization="虚构实验室", role_title="成员",
        value_json={"text": "使用 SolidWorks 完成装配体建模"}, source_text="",
        claim_type="action", evidence_json={}, verification_status="user_confirmed",
    )]
    drafts = [{"id": "m-draft", "kind": "project", "title": "待补全项目",
               "summary": "尝试用 Python 分析数据", "details": {"tools": "pandas"}}]
    confirmed_row = build_project_story_inputs(facts, [], REQUIREMENTS, [])[0]
    draft_row = build_project_story_inputs([], drafts, REQUIREMENTS, [])[0]
    blank_row = build_project_story_inputs([], [], REQUIREMENTS, [])[0]
    assert confirmed_row["schema_version"] == 1
    assert "不得新增组织、时间、奖项或已取得的实测结果" in confirmed_row["design_supplement"]
    assert "open_questions" in draft_row["design_supplement"]
    assert draft_row["material_summary"] == "尝试用 Python 分析数据"
    assert draft_row["material_details"] == {"tools": "pandas"}
    assert "所有结果为 target" in blank_row["design_supplement"]
    assert blank_row["story_boundary"].startswith("这是待完成的蓝图项目")


def test_assembled_placeholder_story_fails_the_delivery_contract():
    """Known filler must fail the gate, not merely be reported as a diagnostic.

    Task 17.3 promotes the previously advisory placeholder diagnostics to hard
    failures: a generic "fill this in" project is not a deliverable STAR story
    and must never reach ready or degraded.
    """
    content = _content()
    story = next(iter_project_stories(content))[2]
    story.update(
        {
            "situation": {
                "context": "围绕目标岗位设计一段可验证的项目实践",
                "problem": "需要把岗位要求转为可拆分、可验证的项目产出",
            },
            "task": {"role": "计划负责人", "goal": "形成可演示、可复盘的项目交付"},
            "actions": [
                {
                    "step": "先定义输入、输出和验证方式，再按阶段保留过程记录",
                    "method": "说明该方法如何服务项目目标",
                    "contribution": "本人负责的已确认部分",
                }
            ],
            "result": {
                "deliverables": ["可演示的项目产出"],
                "verification_method": "用交付物、过程记录和验收条件逐项核验",
            },
        }
    )
    report = _review(content)
    assert report["hard_passed"] is False
    assert report["status"] == "blocked"
    assert any("不具体" in issue or "不完整" in issue for issue in report["issues"])
    # The filler is still located for the developer-facing report.
    diagnostics = report["star_diagnostics"]
    assert diagnostics
    assert all(item["project_id"] == story["project_id"] for item in diagnostics)
    assert all(item["bullet_ids"] == story["bullet_ids"] for item in diagnostics)


def test_one_complete_action_or_metric_does_not_hide_another_incomplete_one():
    content = _content()
    story = _concrete_story(content)
    story["actions"].append({"step": "输出冲突明细表", "method": "写入独立 CSV 文件",
                             "contribution": "计划负责导出脚本"})
    story["result"]["metrics"].append({"name": "运行时间", "value": "待测量", "kind": "target"})
    report = _review(content)
    assert report["hard_passed"] is True
    fields = {item["field"] for item in report["star_diagnostics"]}
    assert {"actions.1.rationale", "actions.1.difficulty", "result.metrics.1.conditions"} <= fields
    assert "actions.0.rationale" not in fields
    assert "result.metrics.0.conditions" not in fields


def test_concrete_non_numeric_project_has_no_placeholder_diagnostics():
    content = _content()
    story = _concrete_story(content)
    story["result"]["metrics"] = []
    report = _review(content)
    assert report["hard_passed"] is True
    assert report["star_diagnostics"] == []


def test_vague_four_word_fields_are_located_without_claiming_semantic_validation():
    content = _content()
    story = _concrete_story(content)
    story["situation"] = {"context": "业务需要", "problem": "效果不好"}
    story["task"]["goal"] = "负责开发"
    story["actions"][0]["method"] = "使用工具"
    story["result"]["verification_method"] = "效果良好"
    fields = {item["field"] for item in _review(content)["star_diagnostics"]}
    assert {"situation.context", "situation.problem", "task.goal",
            "actions.0.method", "result.verification_method"} <= fields


def test_tool_list_copy_flags_dropped_task_and_result_mapping():
    content = _content()
    story = _concrete_story(content)
    bullet = content["sections"][0]["items"][0]["bullets"][0]
    bullet["text"] = "Python、Excel、SQL"
    report = _review(content)
    assert report["hard_passed"] is True
    diagnostics = [
        item for item in report["star_diagnostics"]
        if str(item["field"]).startswith("visible_coverage.")
    ]
    fields = {item["field"] for item in diagnostics}
    assert {"visible_coverage.task", "visible_coverage.result"} <= fields
    assert all(item["project_id"] == story["project_id"] for item in diagnostics)
    assert all(item["bullet_ids"] == [bullet["id"]] for item in diagnostics)
    assert all(item["bullet_ids"] == story["bullet_ids"] for item in diagnostics)


def test_visible_coverage_is_quiet_when_copy_keeps_star_elements():
    content = _content()
    _concrete_story(content)
    fields = {item["field"] for item in _review(content)["star_diagnostics"]}
    assert not any(str(field).startswith("visible_coverage.") for field in fields)


def test_visible_coverage_needs_more_than_a_bullet_id_mapping():
    content = _content()
    story = _concrete_story(content)
    bullet = content["sections"][0]["items"][0]["bullets"][0]
    # The id mapping is intact, yet only a tool name remains in the copy.
    assert story["bullet_ids"] == [bullet["id"]]
    bullet["text"] = "MATLAB"
    fields = {item["field"] for item in _review(content)["star_diagnostics"]}
    assert "visible_coverage.result" in fields


def _critic_output(dimensions=None, *, project_id="", bullet_ids=None):
    return QualityCriticOutput.model_validate({
        "dimensions": dimensions
        if dimensions is not None
        else {name: {"score": 95, "notes": []} for name in QUALITY_DIMENSIONS},
        "summary": "整体优秀",
        "recommendations": [{
            "project_id": project_id,
            "bullet_id": (bullet_ids or [""])[0],
            "suggestion": "补充方法如何解释声明的结果",
        }],
        "project_reviews": [{
            "project_id": project_id,
            "bullet_ids": bullet_ids or [],
            "diagnosis": "行动使用固定区间去重，却声称消除了全部异常，因果不成立",
            "suggestions": ["说明异常判定的测量口径"],
        }],
    })


def test_critic_surfaces_action_result_contradiction_without_auto_rewrite(monkeypatch):
    content = _content()
    story = _concrete_story(content)
    captured = {}

    async def fake_generate_structured(**kwargs):
        captured["payload"] = kwargs["user_payload"]
        return _critic_output(project_id=story["project_id"], bullet_ids=story["bullet_ids"]), "compatible"

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["hard_passed"] is True
    # Local checks stay quiet: they cannot judge whether this method supports
    # the claimed result.  The model critique carries that causal judgement.
    assert report["star_diagnostics"] == []
    review = report["project_reviews"][0]
    assert review["project_id"] == story["project_id"]
    assert review["diagnosis"] == "行动使用固定区间去重，却声称消除了全部异常，因果不成立"
    assert captured["payload"]["project_stories"][0]["project_id"] == story["project_id"]
    assert captured["payload"]["star_diagnostics"] == []
    # The critique is explanatory only: the saved copy is not rewritten.
    assert next(iter_project_stories(content))[2]["situation"]["context"] == "课程传感器采样表存在重复时间戳"


def test_high_critic_scores_do_not_override_a_local_hard_failure(monkeypatch):
    content = {
        "content_version": 3,
        "factuality_policy": "ai_expansion",
        "project_story_contract_version": 1,
        "kind": "target",
        "headline": "数据分析实习生",
        "sections": [{
            "name": "项目/科研/竞赛",
            "items": [{
                "organization": "目标实践",
                "bullets": [{
                    "id": "b-no-story", "text": "完成目标项目", "source_fact_ids": [],
                    "source_target_ids": ["r-data"], "requirement_ids": ["r-data"],
                    "achieved": False, "locked": False, "new_claims": [],
                    "verification_status": "ai_generated",
                }],
            }],
        }],
    }

    async def fake_generate_structured(**_kwargs):
        return _critic_output(), "compatible"

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["hard_passed"] is False
    assert report["status"] == "blocked"
    assert any("缺少完整 STAR 故事" in issue for issue in report["issues"])
    assert all(item["score"] == 95 for item in report["dimensions"].values())


def test_missing_critic_dimensions_are_not_backfilled_with_fake_scores(monkeypatch):
    content = _content()
    story = _concrete_story(content)
    content_before = deepcopy(content)

    async def fake_generate_structured(**_kwargs):
        return _critic_output(
            {"specificity": {"score": 20, "notes": ["过于笼统"]}},
            project_id=story["project_id"],
            bullet_ids=story["bullet_ids"],
        ), "compatible"

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assessed = {name: item for name, item in report["dimensions"].items() if item["assessed"]}
    assert set(assessed) == {"specificity"}
    for name, item in report["dimensions"].items():
        if name != "specificity":
            assert item["score"] is None and item["assessed"] is False
    # A low score is explanatory: it must not mutate the saved resume copy.
    assert content == content_before


def test_critic_unavailable_falls_back_to_deterministic_report(monkeypatch):
    content = _content()
    _concrete_story(content)

    async def fake_generate_structured(**_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["critic_unavailable"] is True
    assert report["critic_status"] == CRITIC_UNAVAILABLE
    # An unavailable review is recorded as incomplete, never as "no problem".
    assert report["critic_missing_dimensions"] == list(QUALITY_DIMENSIONS)
    assert report["semantic_issues"] == []
    assert report["reviewer"] == "deterministic"
    assert report["recommendations"] == []
    assert report["project_reviews"] == []
    assert all(item["score"] is not None for item in report["dimensions"].values())


def test_complete_critique_is_reported_as_complete(monkeypatch):
    content = _content()
    story = _concrete_story(content)

    async def fake_generate_structured(**_kwargs):
        return _critic_output(project_id=story["project_id"], bullet_ids=story["bullet_ids"]), "compatible"

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["critic_status"] == CRITIC_COMPLETE
    assert report["critic_missing_dimensions"] == []


def test_partial_critique_keeps_findings_and_never_implies_a_clean_review(monkeypatch):
    """A missing dimension must not be read as "this part is fine"."""
    content = _content()
    story = _concrete_story(content)

    async def fake_generate_structured(**_kwargs):
        return _critic_output(
            {"specificity": {"score": 30, "notes": ["过于笼统"]}},
            project_id=story["project_id"],
            bullet_ids=story["bullet_ids"],
        ), "compatible"

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", fake_generate_structured
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["critic_status"] == CRITIC_PARTIAL
    assert "specificity" not in report["critic_missing_dimensions"]
    assert "interview_defensibility" in report["critic_missing_dimensions"]
    # Usable findings survive a partial review.
    assert report["project_reviews"]


def test_only_classified_semantic_issues_justify_a_background_repair(monkeypatch):
    content = _content()
    story = _concrete_story(content)

    async def unclassified(**_kwargs):
        return _critic_output(
            project_id=story["project_id"], bullet_ids=story["bullet_ids"]
        ), "compatible"

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", unclassified
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    # A diagnosis without a recognised issue code stays explanatory.
    assert report["project_reviews"][0]["diagnosis"]
    assert report["semantic_issues"] == []

    def classified(dimensions=None, **kwargs):
        output = _critic_output(dimensions, **kwargs)
        output.project_reviews[0].issue_code = "action_result_mismatch"
        return output

    async def with_code(**_kwargs):
        return classified(
            project_id=story["project_id"], bullet_ids=story["bullet_ids"]
        ), "compatible"

    monkeypatch.setattr(
        "app.services.quality_service.generate_structured", with_code
    )
    report = asyncio.run(
        evaluate_version_with_critic(
            content=content, facts=[], requirements=REQUIREMENTS, mode="target"
        )
    )
    assert report["semantic_issues"] == [
        {
            "code": "action_result_mismatch",
            "project_id": story["project_id"],
            "bullet_ids": story["bullet_ids"],
            "diagnosis": "行动使用固定区间去重，却声称消除了全部异常，因果不成立",
            "suggestions": ["说明异常判定的测量口径"],
        }
    ]
