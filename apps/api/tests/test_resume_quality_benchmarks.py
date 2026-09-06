"""Fictional STEM quality benchmarks. No real authorized materials."""

from app.services.bundle_service import _fallback_version
from app.services.quality_service import evaluate_version
from types import SimpleNamespace

BENCHMARKS = {
    "mechanical": {
        "headline": "机械设计工程师",
        "fact": "使用 SolidWorks 完成装配体建模并输出工程图",
        "requirement": "要求熟悉 SolidWorks 并能输出装配体",
    },
    "automation": {
        "headline": "电气自动化工程师",
        "fact": "跟随师傅完成 PLC 点检并记录报警代码",
        "requirement": "要求熟悉 PLC 点检与故障记录",
    },
    "computing": {
        "headline": "数据分析实习生",
        "fact": "用 Python 清洗实验数据并输出汇总表",
        "requirement": "要求使用 Python 处理数据",
    },
    "biomedical": {
        "headline": "生物医药工艺助理",
        "fact": "按SOP记录培养基配制步骤并核对批号",
        "requirement": "要求熟悉培养基配制与批记录",
    },
}


def _fact(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="fact-bench",
        verification_status="user_confirmed",
        category="projects",
        label="课程练习",
        value_json={"text": text},
        source_text=text,
        organization="示例大学实验室",
        role_title="课程负责人",
        location="",
        start_date="2025-03",
        end_date="2025-06",
    )


def test_four_stem_fictional_benchmarks_pass_hard_gates():
    for name, case in BENCHMARKS.items():
        facts = [_fact(case["fact"])]
        requirements = [
            {
                "id": f"req-{name}",
                "text": case["requirement"],
                "priority": "high",
                "category": "must_have",
                "sources": [{"job_id": "job", "evidence": case["requirement"]}],
            }
        ]
        submittable = _fallback_version(
            facts, requirements, kind="submittable", headline=case["headline"], contact={"name": "测试同学"}
        )
        target = _fallback_version(
            facts, requirements, kind="target", headline=case["headline"], contact={"name": "测试同学"}
        )
        sub_report = evaluate_version(
            content=submittable, facts=facts, requirements=requirements, mode="submittable"
        )
        tgt_report = evaluate_version(
            content=target, facts=facts, requirements=requirements, mode="target"
        )
        assert sub_report["hard_passed"], (name, sub_report["issues"])
        assert tgt_report["hard_passed"], (name, tgt_report["issues"])
        encoded = str(submittable) + str(target)
        assert "岑远轩" not in encoded
        assert "@gmail" not in encoded
