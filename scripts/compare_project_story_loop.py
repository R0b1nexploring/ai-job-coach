#!/usr/bin/env python3
"""A/B the v3 project-STAR writer on fictional inputs with the real Provider.

Variant A approximates the pre-plan behaviour (no per-project plan inputs and
none of the design-boundary prompt lines).  Variant B is the current pipeline.
Artifacts go to ``tmp/generated/`` and never contain real personal material.
Nothing is printed beyond aggregate, non-identifying diagnostics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import get_settings
from app.services import bundle_service
from app.services.content_contract import iter_project_stories
from app.services.quality_service import _has_project_detail

NEW_PROMPT_LINES = (
    (
        "project_story 用 design_assumptions 记录没有个人来源、由 AI 补充的设计细节，"
        "用 open_questions 记录尚待本人核实或验证的方法、指标与假设；没有就不填，不得编造。"
    ),
    "每个输入的 design_supplement 说明该项目的设计边界，按来源区分已确认事实、草稿与虚拟目标，不得越界。",
    "信息不足时缩小项目范围，而不是补出未经验证的细节或数字。",
)

REQUIREMENTS = [
    {
        "id": "r-cad",
        "text": "熟练使用 SolidWorks 完成零件与装配设计",
        "category": "skill",
        "priority": "high",
        "frequency": 2,
        "sources": [{"job_id": "j-fictional", "evidence": "熟练使用 SolidWorks"}],
    },
    {
        "id": "r-verify",
        "text": "能够编写设计验证记录并解释关键取舍",
        "category": "responsibility",
        "priority": "high",
        "frequency": 1,
        "sources": [{"job_id": "j-fictional", "evidence": "编写设计验证记录"}],
    },
]

JOB_CONTEXT = [{
    "job_id": "j-fictional",
    "company_name": "虚构精工有限公司",
    "title": "机械设计助理工程师",
    "raw_jd": "职责：机械结构设计与工程图输出。要求：SolidWorks、设计验证记录。",
}]

SPARSE_FACT = SimpleNamespace(
    id="f-fixture",
    category="projects",
    label="夹具课程项目",
    organization="虚构理工大学",
    role_title="项目成员",
    location="杭州",
    start_date="2025-03",
    end_date="2025-06",
    value_json={"text": "使用 SolidWorks 完成夹具结构设计并输出工程图"},
    source_text="使用 SolidWorks 完成夹具结构设计并输出工程图",
    verification_status="user_confirmed",
    material_id="m-fixture",
    claim_type="action",
    evidence_json={"artifact": "课程验收记录"},
)

CASES = {
    "sparse": {
        "facts": [SPARSE_FACT],
        "draft_materials": [],
        "requirements": REQUIREMENTS,
        "job_context": JOB_CONTEXT,
        "headline": "机械设计助理工程师",
        "contact": {"name": "虚构用户", "email": "fictional@example.test", "city": "杭州"},
    },
    "blank": {
        "facts": [],
        "draft_materials": [],
        "requirements": REQUIREMENTS,
        "job_context": JOB_CONTEXT,
        "headline": "机械设计助理工程师",
        "contact": {"name": "虚构用户", "email": "fictional@example.test", "city": "杭州"},
    },
}


def _project_plan_summary(content: dict) -> list[dict]:
    rows = []
    for _section, _item, story in iter_project_stories(content):
        situation = story.get("situation") or {}
        task = story.get("task") or {}
        actions = [a for a in story.get("actions") or [] if isinstance(a, dict)]
        result = story.get("result") or {}
        rows.append({
            "project_id": story.get("project_id"),
            "title": story.get("title"),
            "achieved": story.get("achieved"),
            "design_assumptions": list(story.get("design_assumptions") or []),
            "open_questions": list(story.get("open_questions") or []),
            "concrete_fields": {
                "situation": _has_project_detail(situation.get("context")) and _has_project_detail(situation.get("problem")),
                "task": _has_project_detail(task.get("goal")),
                "actions": all(_has_project_detail(a.get("method")) for a in actions) if actions else False,
                "result": _has_project_detail(result.get("verification_method")),
            },
            "concrete_action_count": sum(
                1 for a in actions
                if _has_project_detail(a.get("method")) and _has_project_detail(a.get("rationale"))
            ),
            "action_count": len(actions),
        })
    return rows


def _summarize(content: dict, report: dict) -> dict:
    bullets = [
        str(b.get("text") or "")
        for section in content.get("sections") or []
        for item in section.get("items") or []
        for b in item.get("bullets") or []
    ]
    star_diagnostics = report.get("star_diagnostics") or []
    visible_coverage = [d for d in star_diagnostics if str(d.get("field", "")).startswith("visible_coverage.")]
    return {
        "status": report.get("status"),
        "hard_passed": report.get("hard_passed"),
        "reviewer": report.get("reviewer"),
        "critic_unavailable": report.get("critic_unavailable"),
        "dimension_scores": {
            name: (item or {}).get("score") for name, item in (report.get("dimensions") or {}).items()
        },
        "project_reviews": len(report.get("project_reviews") or []),
        "bullets": len(bullets),
        "projects": _project_plan_summary(content),
        "star_diagnostic_fields": [d.get("field") for d in star_diagnostics],
        "visible_coverage_fields": [d.get("field") for d in visible_coverage],
    }


def _old_prompt(current: str) -> str:
    text = current
    for line in NEW_PROMPT_LINES:
        text = text.replace(line, "")
    return text


async def _run_variant(case: dict, *, with_plan: bool, attempts: int = 5) -> dict:
    """Retry until both kinds come from the real model.

    The configured compatible provider intermittently returns an invalid
    structured pair (``LLM_MALFORMED_RESPONSE``); those runs fall back to the
    deterministic local content and would corrupt an A/B comparison.
    """
    original_builder = bundle_service.build_project_story_inputs
    original_prompt = bundle_service.RESUME_REWRITE_PAIR_PROMPT
    if not with_plan:
        bundle_service.build_project_story_inputs = lambda *a, **k: []
        bundle_service.RESUME_REWRITE_PAIR_PROMPT = _old_prompt(original_prompt)
    used = 0
    try:
        for used in range(1, attempts + 1):
            result = await bundle_service._compose_pair(deepcopy(case))
            if result.get("sub_source") == "model" and result.get("tgt_source") == "model":
                result["_attempts_used"] = used
                return result
    finally:
        bundle_service.build_project_story_inputs = original_builder
        bundle_service.RESUME_REWRITE_PAIR_PROMPT = original_prompt
    result["_attempts_used"] = used
    return result


async def _run_case(name: str, case: dict) -> dict:
    before = await _run_variant(case, with_plan=False)
    after = await _run_variant(case, with_plan=True)
    return {
        "case": name,
        "before": {
            "bundle_status": before.get("status"),
            "sub_source": before.get("sub_source"),
            "tgt_source": before.get("tgt_source"),
            "attempts_used": before.get("_attempts_used"),
            "repair_history": before.get("repair_history"),
            "target": _summarize(before["target"], before["tgt_report"]),
            "submittable": _summarize(before["submittable"], before["sub_report"]),
        },
        "after": {
            "bundle_status": after.get("status"),
            "sub_source": after.get("sub_source"),
            "tgt_source": after.get("tgt_source"),
            "attempts_used": after.get("_attempts_used"),
            "repair_history": after.get("repair_history"),
            "target": _summarize(after["target"], after["tgt_report"]),
            "submittable": _summarize(after["submittable"], after["sub_report"]),
        },
        "artifacts": {
            "before_target": before["target"],
            "after_target": after["target"],
            "before_submittable": before["submittable"],
            "after_submittable": after["submittable"],
        },
        "full": {
            "before": {
                "target": before["target"],
                "submittable": before["submittable"],
                "tgt_report": _report_text(before["tgt_report"]),
                "sub_report": _report_text(before["sub_report"]),
            },
            "after": {
                "target": after["target"],
                "submittable": after["submittable"],
                "tgt_report": _report_text(after["tgt_report"]),
                "sub_report": _report_text(after["sub_report"]),
            },
        },
    }


def _report_text(report: dict) -> dict:
    return {
        "status": report.get("status"),
        "hard_passed": report.get("hard_passed"),
        "issues": report.get("issues"),
        "reviewer": report.get("reviewer"),
        "critic_summary": report.get("critic_summary"),
        "star_diagnostics": report.get("star_diagnostics"),
        "recommendations": report.get("recommendations"),
        "project_reviews": report.get("project_reviews"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="虚构数据下的项目 STAR 真实模型 A/B")
    parser.add_argument("--acknowledge-cost", action="store_true", help="确认会调用已配置的真实 LLM Provider")
    parser.add_argument("--case", choices=sorted(CASES), default="sparse")
    parser.add_argument("--verbose", action="store_true", help="输出不含 Prompt/正文/密钥的 Provider 元数据")
    args = parser.parse_args()
    if not args.acknowledge_cost:
        print("拒绝执行：请显式添加 --acknowledge-cost。", file=sys.stderr)
        return 2
    if args.verbose:
        logger = logging.getLogger("app.llm")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    settings = get_settings()
    if settings.llm_provider.strip().lower() != "compatible":
        print("拒绝执行：LLM_PROVIDER 必须为 compatible。", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "tmp" / "generated" / f"project-story-compare-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(_run_case(args.case, CASES[args.case]))
    (out_dir / "compare.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "case": args.case,
        "model": settings.model_for("resume_rewrite"),
        "out_dir": str(out_dir.relative_to(ROOT)),
        "before": report["before"],
        "after": report["after"],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
