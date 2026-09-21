"""Writer profile and undergraduate resource boundary (tasks 18.1-18.4, narrowed).

The goal is narrow: a designed (blueprint) project must not exceed what the
candidate can actually do, and it should reuse the candidate's own declared
background and tools. All inputs here are fictional.
"""

import json

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.routes.core import FactCreateIn
from app.services.bundle_service import build_writer_profile
from app.services.quality_service import _resource_overreach, evaluate_version


def _fact(fid, category, label, organization, role, text, *, status="user_confirmed"):
    return SimpleNamespace(
        id=fid, category=category, label=label, organization=organization,
        role_title=role, location="", start_date="", end_date="",
        value_json={"text": text}, source_text=text, verification_status=status,
        material_id=f"mat-{fid}", claim_type="", evidence_json={},
    )


MECHANICAL_FACTS = [
    _fact("f-edu", "education", "机械工程本科", "示例理工大学", "学生",
          "机械工程本科在读，学过机械设计基础与工程制图"),
    _fact("f-design", "projects", "减速箱课程设计", "示例理工大学", "本人",
          "用 SolidWorks 完成小型减速箱零件建模与装配，输出装配体与二维工程图"),
    _fact("f-machining", "employment", "校内工训中心加工实训", "示例理工大学工训中心", "实训学生",
          "完成普通车削与钻削工序，记录加工参数并检查尺寸"),
]

DESIGN_REQS = [
    {"id": "r-1", "text": "负责产品结构方案设计与三维建模", "priority": "high", "frequency": 2},
    {"id": "r-2", "text": "输出装配体与二维工程图并标注尺寸公差", "priority": "high", "frequency": 2},
]
SIMULATION_REQS = [
    {"id": "s-1", "text": "完成有限元强度仿真并输出应力云图", "priority": "high", "frequency": 1},
]


def test_profile_carries_the_candidates_own_background_and_tools():
    profile = build_writer_profile(MECHANICAL_FACTS, [], DESIGN_REQS)
    assert profile["profile_version"] == 1
    assert any("示例理工大学" in item for item in profile["declared_background"])
    assert "SolidWorks" in profile["declared_tools"]
    assert "减速箱课程设计" in profile["material_titles"]


def test_placeholder_role_labels_are_not_echoed():
    """A two-character "本人" adds nothing and should not reach the writer."""
    profile = build_writer_profile(MECHANICAL_FACTS, [], DESIGN_REQS)
    assert all("本人" not in item for item in profile["past_work"])
    assert any("工训中心" in item for item in profile["past_work"])


def test_resource_boundary_flags_capabilities_the_candidate_cannot_evidence():
    profile = build_writer_profile(MECHANICAL_FACTS, [], SIMULATION_REQS)
    boundary = profile["resource_boundary"]
    assert any("专业仿真" in item for item in boundary["evidence_required"])
    # The candidate's real CAD work is not treated as a simulation claim.
    design_profile = build_writer_profile(MECHANICAL_FACTS, [], DESIGN_REQS)
    assert design_profile["resource_boundary"]["evidence_required"] == []


def test_boundary_states_the_default_assumptions_and_prohibitions():
    boundary = build_writer_profile(MECHANICAL_FACTS, [], DESIGN_REQS)["resource_boundary"]
    assert any("电脑" in item for item in boundary["assume_available"])
    assert any("实验室" in item for item in boundary["forbidden"])
    assert any("仿真" in item for item in boundary["forbidden"])
    # Real evidence is explicitly protected from being downgraded.
    assert "不因学历降级" in boundary["note"]


def test_real_simulation_work_is_not_flagged_as_overreach():
    """A candidate who genuinely did simulation keeps it (no stereotyping)."""
    facts = MECHANICAL_FACTS + [
        _fact("f-sim", "projects", "课程有限元作业", "示例理工大学", "本人",
              "用 ANSYS 完成支架静力分析，输出应力云图并核对网格无关性"),
    ]
    profile = build_writer_profile(facts, [], SIMULATION_REQS)
    # The requirement is now evidenced, so it is not an open gap.
    assert profile["resource_boundary"]["evidence_required"] == []


def test_overreach_detector_flags_lab_language_deterministically():
    """The detector itself is narrow and keyword-based, not a quality verdict."""
    story = {
        "situation": {"context": "完成样品制备与拉伸试验", "problem": "需要实测数据"},
        "task": {"goal": "输出实测性能曲线"},
        "actions": [{"step": "样品制备", "method": "拉伸试验", "difficulty": "夹具对中"}],
        "result": {"deliverables": ["实测报告"], "verification_method": "重复试验", "metrics": []},
    }
    assert _resource_overreach(story, []) == ["实验室实测"]


def test_designed_project_needing_a_lab_fails_the_delivery_contract():
    content = {
        "content_version": 3,
        "factuality_policy": "ai_expansion",
        "project_story_contract_version": 1,
        "kind": "target",
        "headline": "机械设计工程师",
        "sections": [{
            "name": "项目/科研/竞赛",
            "items": [{
                "organization": "目标实践",
                "bullets": [{
                    "id": "b1", "text": "完成样品制备与拉伸试验并输出实测性能曲线",
                    "source_fact_ids": [], "source_target_ids": ["r-1"],
                    "requirement_ids": ["r-1"], "achieved": False, "locked": False,
                    "new_claims": [], "verification_status": "ai_generated",
                }],
                "project_story": {
                    "schema_version": 1, "project_id": "p1", "achieved": False,
                    "bullet_ids": ["b1"], "source_fact_ids": [], "source_target_ids": ["r-1"],
                    "requirement_ids": ["r-1"],
                    "situation": {
                        "context": "需要测定材料在拉伸载荷下的真实性能表现",
                        "problem": "缺少可靠的实测数据支撑设计选型",
                    },
                    "task": {"role": "负责样品制备与试验执行", "goal": "输出实测性能曲线与结论"},
                    "actions": [{
                        "step": "按标准制备拉伸试样", "method": "使用万能试验机加载并记录曲线",
                        "contribution": "本人负责制备与试验", "rationale": "标准试样保证可比性",
                        "difficulty": "夹具对中影响结果",
                    }],
                    "result": {
                        "deliverables": ["实测性能曲线与试验报告"],
                        "verification_method": "重复试验并核对离散度", "metrics": [],
                    },
                },
            }],
        }],
    }
    report = evaluate_version(
        content=content, facts=[],
        requirements=[{"id": "r-1", "text": "材料性能测试", "priority": "high"}],
        mode="target",
    )
    assert report["hard_passed"] is False
    assert any("超出本人可及资源" in issue for issue in report["issues"])


def test_designed_project_within_reach_passes():
    content = {
        "content_version": 3,
        "factuality_policy": "ai_expansion",
        "project_story_contract_version": 1,
        "kind": "target",
        "headline": "机械设计工程师",
        "sections": [{
            "name": "项目/科研/竞赛",
            "items": [{
                "organization": "目标实践",
                "bullets": [{
                    "id": "b1", "text": "用公开手册参数完成联轴器选型比较并给出选择理由",
                    "source_fact_ids": [], "source_target_ids": ["r-1"],
                    "requirement_ids": ["r-1"], "achieved": False, "locked": False,
                    "new_claims": [], "verification_status": "ai_generated",
                }],
                "project_story": {
                    "schema_version": 1, "project_id": "p1", "achieved": False,
                    "bullet_ids": ["b1"], "source_fact_ids": [], "source_target_ids": ["r-1"],
                    "requirement_ids": ["r-1"],
                    "situation": {
                        "context": "课程设计需要为传动轴选择合适联轴器",
                        "problem": "两种候选方案的载荷与安装空间约束不同，需要可解释的比较",
                    },
                    "task": {"role": "负责整理参数并完成比较", "goal": "输出选型比较与选择理由"},
                    "actions": [{
                        "step": "整理两种方案的公开手册参数",
                        "method": "按额定转矩、转速与安装空间列出对照表",
                        "contribution": "本人负责参数整理与比较", "rationale": "公开参数可直接核对",
                        "difficulty": "两种方案侧重不同指标",
                    }],
                    "result": {
                        "deliverables": ["联轴器选型对照表与选择说明"],
                        "verification_method": "逐项核对参数来源与约束是否满足", "metrics": [],
                    },
                },
            }],
        }],
    }
    report = evaluate_version(
        content=content, facts=[],
        requirements=[{"id": "r-1", "text": "联轴器选型", "priority": "high"}],
        mode="target",
    )
    assert report["hard_passed"] is True, report["issues"]


def test_fact_category_is_restricted_to_the_canonical_vocabulary():
    """An unknown category used to be stored and misfiled under 项目/科研/竞赛."""
    for category in ("education", "employment", "projects", "skills", "certificates", "other"):
        assert FactCreateIn(category=category, label="示例", value_json={}).category == category
    with pytest.raises(ValidationError):
        FactCreateIn(category="internships", label="示例", value_json={})


def test_only_the_blueprint_marks_unachieved_bullets():
    """Spec: the submittable resume must not display the unachieved marker.

    Regression: the marker rule exempted AI-expansion bullets only when they
    cited no requirement, but the submittable path clears requirement ids, so
    blueprint-style gaps leaked a visible `*` into the job-seeking version.
    """
    from app.services.resume_style import blueprint_footer, should_mark_unachieved

    cited = {"achieved": False, "verification_status": "ai_generated", "requirement_ids": ["p-1"]}
    uncited = {"achieved": False, "verification_status": "ai_generated", "requirement_ids": []}
    submittable = {"kind": "submittable", "factuality_policy": "ai_expansion", "content_version": 3}
    target = {"kind": "target", "factuality_policy": "ai_expansion", "content_version": 3}

    assert should_mark_unachieved(submittable, cited) is False
    assert should_mark_unachieved(submittable, uncited) is False
    # The blueprint keeps the marker on its gaps only.
    assert should_mark_unachieved(target, cited) is True
    assert should_mark_unachieved(target, uncited) is False

    sub_content = {**submittable, "sections": [{"items": [{"bullets": [cited]}]}]}
    tgt_content = {**target, "sections": [{"items": [{"bullets": [cited]}]}]}
    assert blueprint_footer(sub_content) == ""
    assert blueprint_footer(tgt_content)
