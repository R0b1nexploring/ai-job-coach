#!/usr/bin/env python3
"""Accumulate fictional real-Provider resume samples for the v3 STAR pipeline.

Five directions: mechanical, computer, AI, electronics, electrical.  Each
sample runs the current ``_compose_pair`` pipeline with a fictional profile and
either two confirmed project facts (sparse/medium) or no material (blank).
Only fictional data is used; artifacts stay in gitignored ``tmp/generated/``.
The run is resumable: existing ``sample-NNN.json`` files are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("RESUME_QUALITY_GATE_ENABLED", "true")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import get_settings
from app.services import bundle_service
from app.services.content_contract import iter_project_stories
from app.services.quality_service import _has_project_detail


def _req(req_id, text, priority="high", frequency=1, evidence=""):
    return {
        "id": req_id,
        "text": text,
        "category": "skill",
        "priority": priority,
        "frequency": frequency,
        "sources": [{"job_id": "j-fictional", "evidence": evidence or text}],
    }


def _fact(fact_id, label, organization, role_title, start, end, text, artifact):
    return SimpleNamespace(
        id=fact_id,
        category="projects",
        label=label,
        organization=organization,
        role_title=role_title,
        location="虚构城市",
        start_date=start,
        end_date=end,
        value_json={"text": text},
        source_text=text,
        verification_status="user_confirmed",
        material_id=f"m-{fact_id}",
        claim_type="action",
        evidence_json={"artifact": artifact},
    )


def _case(direction, suffix, title, company, raw_jd, requirements, facts):
    return {
        "name": f"{direction}-{suffix}",
        "direction": direction,
        "job_context": [{
            "job_id": "j-fictional",
            "company_name": company,
            "title": title,
            "raw_jd": raw_jd,
        }],
        "requirements": requirements,
        "facts": facts,
        "draft_materials": [],
        "headline": title,
        "contact": {
            "name": "虚构样本",
            "email": "fictional@example.test",
            "city": "虚构城市",
        },
    }


def build_cases() -> list[dict]:
    mechanical = _case(
        "mechanical", "medium", "机械设计助理工程师", "虚构精工有限公司",
        "职责：机械结构设计与工程图输出，编写设计验证记录。要求：SolidWorks、机械制图。",
        [
            _req("mech-cad", "熟练使用 SolidWorks 完成零件与装配设计", frequency=2),
            _req("mech-doc", "能够编写设计验证记录并解释关键取舍"),
        ],
        [
            _fact("mech-f1", "减速器课程设计", "虚构理工大学", "项目成员", "2025-03", "2025-06",
                  "使用 SolidWorks 完成二级减速器装配建模并输出装配图与零件图", "课程验收记录"),
            _fact("mech-f2", "夹具设计练习", "虚构理工大学", "课程学生", "2024-09", "2024-12",
                  "设计钻孔夹具结构，绘制定位与夹紧方案工程图", "课程图纸与评语"),
        ],
    )
    computer = _case(
        "computer", "medium", "后端开发实习生", "虚构网络科技有限公司",
        "职责：参与后端接口与数据库设计。要求：Java/Spring Boot、SQL、Git。",
        [
            _req("cs-java", "使用 Java 与 Spring Boot 开发后端接口", frequency=2),
            _req("cs-sql", "设计关系型数据库表结构并编写查询"),
        ],
        [
            _fact("cs-f1", "校园失物招领系统", "虚构理工大学", "后端负责人", "2025-02", "2025-05",
                  "使用 Spring Boot 实现失物登记与认领接口，MySQL 存储数据", "课程答辩记录"),
            _fact("cs-f2", "数据库课程设计", "虚构理工大学", "课程学生", "2024-09", "2024-12",
                  "设计图书借阅数据库表结构与视图，编写 SQL 查询与存储过程", "课程设计报告"),
        ],
    )
    ai = _case(
        "ai", "medium", "算法实习生", "虚构智能科技有限公司",
        "职责：参与数据清洗与模型训练。要求：Python、PyTorch、数据处理。",
        [
            _req("ai-python", "使用 Python 清洗与整理实验数据", frequency=2),
            _req("ai-train", "使用 PyTorch 训练并评估模型"),
        ],
        [
            _fact("ai-f1", "图像分类课程项目", "虚构理工大学", "模型训练成员", "2025-03", "2025-06",
                  "使用 PyTorch 训练图像分类模型，记录数据增强与评估结果", "课程报告与实验记录"),
            _fact("ai-f2", "实验数据清洗脚本", "虚构理工大学", "课程学生", "2024-10", "2024-12",
                  "使用 pandas 清洗传感器采样数据并输出异常记录", "清洗脚本与日志"),
        ],
    )
    electronics = _case(
        "electronics", "medium", "硬件设计实习生", "虚构电子科技有限公司",
        "职责：参与嵌入式硬件与电路设计。要求：STM32、C 语言、Altium Designer。",
        [
            _req("ee-mcu", "使用 STM32 完成嵌入式功能开发", frequency=2),
            _req("ee-pcb", "使用 Altium Designer 完成原理图与 PCB 设计"),
        ],
        [
            _fact("ee-f1", "单片机温控系统", "虚构理工大学", "嵌入式负责人", "2025-03", "2025-06",
                  "使用 STM32 与温度传感器实现闭环温控并记录调试数据", "课程实物与调试记录"),
            _fact("ee-f2", "PCB 课程设计", "虚构理工大学", "课程学生", "2024-09", "2024-12",
                  "使用 Altium Designer 设计电源模块原理图与双层 PCB", "设计文件与验收记录"),
        ],
    )
    electrical = _case(
        "electrical", "medium", "电气自动化助理工程师", "虚构电气设备有限公司",
        "职责：参与电气控制与配电设计。要求：PLC、变频器、电气图纸。",
        [
            _req("ep-plc", "使用 PLC 完成电气控制逻辑设计", frequency=2),
            _req("ep-drawing", "绘制与阅读电气控制图纸"),
        ],
        [
            _fact("ep-f1", "电机控制课程设计", "虚构理工大学", "项目成员", "2025-02", "2025-05",
                  "使用 PLC 与变频器实现电机启停与调速控制，记录联调过程", "联调记录与评分"),
            _fact("ep-f2", "配电柜接线实训", "虚构职业技术学院", "实训学生", "2024-07", "2024-08",
                  "按电气图纸完成配电柜元器件接线与通电检查", "实训验收记录"),
        ],
    )
    directions = [mechanical, computer, ai, electronics, electrical]
    cases: list[dict] = list(directions)
    for base in directions:
        blank = {
            **base,
            "name": f"{base['direction']}-blank",
            "facts": [],
        }
        cases.append(blank)
    return cases


def _plan_summary(content: dict) -> list[dict]:
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
            "concrete": {
                "situation": _has_project_detail(situation.get("context")) and _has_project_detail(situation.get("problem")),
                "task": _has_project_detail(task.get("goal")),
                "actions": all(_has_project_detail(a.get("method")) for a in actions) if actions else False,
                "result": _has_project_detail(result.get("verification_method")),
            },
            "actions": len(actions),
            "concrete_actions": sum(
                1 for a in actions
                if _has_project_detail(a.get("method")) and _has_project_detail(a.get("rationale"))
            ),
            "assumptions": len(story.get("design_assumptions") or []),
            "open_questions": len(story.get("open_questions") or []),
        })
    return rows


def _summarize(content: dict, report: dict) -> dict:
    bullets = [
        str(b.get("text") or "")
        for section in content.get("sections") or []
        for item in section.get("items") or []
        for b in item.get("bullets") or []
    ]
    diagnostics = report.get("star_diagnostics") or []
    return {
        "status": report.get("status"),
        "hard_passed": report.get("hard_passed"),
        "reviewer": report.get("reviewer"),
        "critic_unavailable": report.get("critic_unavailable"),
        "dimensions_assessed": sum(
            1 for item in (report.get("dimensions") or {}).values() if (item or {}).get("assessed")
        ),
        "project_reviews": len(report.get("project_reviews") or []),
        "bullets": bullets,
        "projects": _plan_summary(content),
        "visible_coverage": [
            d.get("field") for d in diagnostics if str(d.get("field", "")).startswith("visible_coverage.")
        ],
        "diagnostic_count": len(diagnostics),
        "recommendation_count": len(report.get("recommendations") or []),
    }


async def _sample(case: dict, *, attempts: int) -> dict:
    used = 0
    result = None
    for used in range(1, attempts + 1):
        result = await bundle_service._compose_pair(dict(case))
        if result.get("sub_source") == "model" and result.get("tgt_source") == "model":
            break
    return {
        "case": case["name"],
        "direction": case["direction"],
        "has_material": bool(case["facts"]),
        "attempts_used": used,
        "writer_source": {
            "submittable": result.get("sub_source"),
            "target": result.get("tgt_source"),
        },
        "bundle_status": result.get("status"),
        "repair_history": result.get("repair_history"),
        "target": _summarize(result["target"], result["tgt_report"]),
        "submittable": _summarize(result["submittable"], result["sub_report"]),
        "content": {
            "target": result["target"],
            "submittable": result["submittable"],
        },
        "reports": {
            "target": {
                "issues": result["tgt_report"].get("issues"),
                "critic_summary": result["tgt_report"].get("critic_summary"),
                "star_diagnostics": result["tgt_report"].get("star_diagnostics"),
                "project_reviews": result["tgt_report"].get("project_reviews"),
            },
            "submittable": {
                "issues": result["sub_report"].get("issues"),
                "critic_summary": result["sub_report"].get("critic_summary"),
            },
        },
    }


def _aggregate(samples: list[dict]) -> dict:
    total = len(samples)
    model_ok = sum(
        1 for s in samples
        if s["writer_source"]["submittable"] == "model" and s["writer_source"]["target"] == "model"
    )
    plans = [p for s in samples for p in s["target"]["projects"]]
    concrete = sum(
        1 for p in plans if all(p["concrete"].values())
    )
    target_dims = sum(1 for s in samples if s["target"]["dimensions_assessed"] > 0)
    return {
        "samples": total,
        "model_writer_samples": model_ok,
        "fallback_samples": total - model_ok,
        "target_project_plans": len(plans),
        "fully_concrete_plans": concrete,
        "visible_coverage_flags": sum(len(s["target"]["visible_coverage"]) for s in samples),
        "samples_with_assessed_dimensions": target_dims,
        "samples_with_project_reviews": sum(1 for s in samples if s["target"]["project_reviews"] > 0),
        "directions": sorted({s["direction"] for s in samples}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="用虚构数据积累真实模型简历样本")
    parser.add_argument("--acknowledge-cost", action="store_true", help="确认会调用已配置的真实 LLM Provider")
    parser.add_argument("--count", type=int, default=20, help="目标样本总数（默认 20）")
    parser.add_argument("--attempts", type=int, default=6, help="单个样本写作者回退时的最大尝试次数")
    parser.add_argument("--out", default="", help="输出目录；默认沿用当天目录以便续跑")
    args = parser.parse_args()
    if not args.acknowledge_cost:
        print("拒绝执行：请显式添加 --acknowledge-cost。", file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.llm_provider.strip().lower() != "compatible":
        print("拒绝执行：LLM_PROVIDER 必须为 compatible。", file=sys.stderr)
        return 2

    if args.out:
        out_dir = Path(args.out)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_dir = ROOT / "tmp" / "generated" / f"resume-samples-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    samples = []
    for index in range(args.count):
        path = out_dir / f"sample-{index:03d}.json"
        if path.exists():
            samples.append(json.loads(path.read_text(encoding="utf-8")))
            continue
        case = cases[index % len(cases)]
        record = asyncio.run(_sample(case, attempts=args.attempts))
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        samples.append(record)
        (out_dir / "aggregate.json").write_text(
            json.dumps(_aggregate(samples), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "index": index,
            "case": record["case"],
            "attempts": record["attempts_used"],
            "source": record["writer_source"]["target"],
            "bundle": record["bundle_status"],
            "projects": len(record["target"]["projects"]),
            "bullets": len(record["target"]["bullets"]),
        }, ensure_ascii=False), flush=True)
    (out_dir / "aggregate.json").write_text(
        json.dumps(_aggregate(samples), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("OUT", str(out_dir.relative_to(ROOT)))
    print(json.dumps(_aggregate(samples), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
