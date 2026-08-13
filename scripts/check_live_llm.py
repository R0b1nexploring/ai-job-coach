#!/usr/bin/env python3
"""Run one explicit, synthetic, paid-provider regression without logging content."""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import get_settings  # noqa: E402
from app.providers.llm.runtime import generate_structured  # noqa: E402
from app.providers.llm.schemas import ResumeExtractionOutput  # noqa: E402
from app.services.application_email import build_email_draft  # noqa: E402
from app.services.capability_service import build_targets  # noqa: E402
from app.services.interview_generator import generate_guarded_interview  # noqa: E402
from app.services.resume_generator import (  # noqa: E402
    generate_guarded_resume,
    generate_resume,
)
from app.services.resume_parser import (  # noqa: E402
    deterministic_extraction,
    sanitize_extraction,
)


@dataclass(frozen=True)
class SyntheticCase:
    name: str
    resume_text: str
    facts: tuple[dict, ...]
    job: dict
    gap: dict


CASES = {
    "mechanical": SyntheticCase(
        name="mechanical",
        resume_text=(
            "姓名：测试甲\n城市：杭州\n邮箱：test-a@example.test\n项目经历\n"
            "虚构理工大学 | 夹具课程项目 | 项目成员 | 杭州 | 2025-03 至 2025-06\n"
            "使用 SolidWorks 完成夹具结构设计并输出工程图\n专业技能\n"
            "使用 CAD 整理机械零件图并编制设计记录"
        ),
        facts=(
            {
                "id": "fact-mechanical-project",
                "category": "projects",
                "label": "夹具课程项目",
                "text": "使用 SolidWorks 完成夹具结构设计并输出工程图",
                "organization": "虚构理工大学",
                "role_title": "项目成员",
                "location": "杭州",
                "start_date": "2025-03",
                "end_date": "2025-06",
            },
            {
                "id": "fact-mechanical-skill",
                "category": "skills",
                "label": "机械制图",
                "text": "使用 CAD 整理机械零件图并编制设计记录",
                "organization": "",
                "role_title": "",
                "location": "",
                "start_date": "",
                "end_date": "",
            },
        ),
        job={
            "title": "机械设计助理工程师",
            "company_name": "虚构精工有限公司",
            "city": "杭州",
            "raw_jd": (
                "职责：负责机械结构设计与工程图输出。\n"
                "要求：熟练使用 SolidWorks；具备有限元分析能力；能够编写设计验证记录。"
            ),
            "responsibilities": ["负责机械结构设计与工程图输出"],
            "must_have": ["熟练使用 SolidWorks", "具备有限元分析能力"],
            "keywords": ["SolidWorks", "有限元分析", "设计验证记录"],
            "work_conditions": ["工作地点为杭州"],
        },
        gap={"requirement": "有限元分析", "category": "skills", "severity": "high"},
    ),
    "bioprocess": SyntheticCase(
        name="bioprocess",
        resume_text=(
            "姓名：测试乙\n城市：苏州\n邮箱：test-b@example.test\n项目经历\n"
            "虚构生物学院 | 发酵数据课程项目 | 项目成员 | 苏州 | 2025-02 至 2025-05\n"
            "使用 Python 分析发酵实验数据并输出数据清洗记录\n专业技能\n"
            "完成生物工程课程设计并编制实验记录"
        ),
        facts=(
            {
                "id": "fact-bioprocess-project",
                "category": "projects",
                "label": "发酵数据课程项目",
                "text": "使用 Python 分析发酵实验数据并输出数据清洗记录",
                "organization": "虚构生物学院",
                "role_title": "项目成员",
                "location": "苏州",
                "start_date": "2025-02",
                "end_date": "2025-05",
            },
            {
                "id": "fact-bioprocess-skill",
                "category": "skills",
                "label": "实验记录",
                "text": "完成生物工程课程设计并编制实验记录",
                "organization": "",
                "role_title": "",
                "location": "",
                "start_date": "",
                "end_date": "",
            },
        ),
        job={
            "title": "生物工艺助理工程师",
            "company_name": "虚构生物技术有限公司",
            "city": "苏州",
            "raw_jd": (
                "职责：协助整理工艺实验数据并维护实验记录。\n"
                "要求：能够使用 Python 处理实验数据；了解 GMP 文档；具备细胞培养基础。"
            ),
            "responsibilities": ["协助整理工艺实验数据并维护实验记录"],
            "must_have": ["能够使用 Python 处理实验数据", "了解 GMP 文档"],
            "keywords": ["Python", "GMP", "实验记录"],
            "work_conditions": ["工作地点为苏州"],
        },
        gap={"requirement": "GMP 文档", "category": "skills", "severity": "high"},
    ),
}


class SmokeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def make_facts(case: SyntheticCase) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=value["id"],
            category=value["category"],
            label=value["label"],
            value_json={"text": value["text"]},
            source_text=value["text"],
            organization=value["organization"],
            role_title=value["role_title"],
            location=value["location"],
            start_date=value["start_date"],
            end_date=value["end_date"],
            provenance="original_resume",
            verification_status="user_confirmed",
        )
        for value in case.facts
    ]


def make_job(case: SyntheticCase) -> SimpleNamespace:
    value = case.job
    return SimpleNamespace(
        title=value["title"],
        company_name=value["company_name"],
        city=value["city"],
        raw_jd=value["raw_jd"],
        responsibilities_json=value["responsibilities"],
        must_have_json=value["must_have"],
        nice_to_have_json=[],
        keywords_json=value["keywords"],
        work_conditions_json=value["work_conditions"],
    )


async def measured(label: str, operation, checks: list[dict]):
    started = monotonic()
    value = await operation
    checks.append({"task": label, "duration_ms": round((monotonic() - started) * 1000)})
    return value


async def run_case(case: SyntheticCase) -> dict:
    settings = get_settings()
    checks: list[dict] = []
    facts = make_facts(case)
    job = make_job(case)
    contact = {
        "name": "测试用户",
        "phone": "",
        "email": "tester@example.test",
        "city": job.city,
    }

    fallback_extraction = deterministic_extraction(case.resume_text)
    extraction_result = await measured(
        "resume_extract",
        generate_structured(
            task="resume_extract",
            system_prompt=(
                "你是简历事实抽取器。text 和 source_text 必须逐字来自输入原文，不得润色；"
                "日期、组织、职位和地点不确定时留空，绝不猜测。按给定结构输出严格 JSON。"
            ),
            user_payload={
                "resume_text": case.resume_text,
                "mock_response": fallback_extraction,
            },
            response_model=ResumeExtractionOutput,
        ),
        checks,
    )
    extraction, extraction_provider = extraction_result
    sanitized = sanitize_extraction(extraction.model_dump(), case.resume_text)
    require(extraction_provider == "compatible", "resume_extract 未直接使用 compatible")
    require(bool(sanitized["facts"]), "resume_extract 没有可追溯事实")
    checks[-1].update(
        provider=extraction_provider, count=len(sanitized["facts"]), guard="passed"
    )

    match = SimpleNamespace(gaps_json=[case.gap])
    target_result = await measured(
        "capability_plan", build_targets(match, job, facts), checks
    )
    target_values, target_provider = target_result
    require(target_provider == "compatible", "capability_plan 触发了回退")
    require(bool(target_values), "capability_plan 没有有效目标")
    require(
        bool(target_values[0]["acceptance_criteria_json"]),
        "capability_plan 缺少验收标准",
    )
    targets = [
        SimpleNamespace(
            id=f"target-{index + 1}",
            status="pending",
            achieved_fact_id=None,
            **value,
        )
        for index, value in enumerate(target_values)
    ]
    checks[-1].update(provider=target_provider, count=len(targets), guard="passed")

    target_result = await measured(
        "resume_target",
        generate_guarded_resume(facts, job, targets, kind="target", contact=contact),
        checks,
    )
    target_content = target_result["content"]
    target_provider = target_result["provider"]
    target_evaluation = target_result["evaluation"]
    require(target_provider == "compatible", "resume_target 触发了 Provider 回退")
    require(target_result["fallback_used"] is False, "resume_target 使用了本地内容回退")
    require(
        target_evaluation["status"] == "passed",
        f"resume_target 未通过本地 Fact Guard：{target_evaluation['issues'][:5]}",
    )
    require(target_evaluation["unachieved_count"] > 0, "resume_target 缺少未达成目标")
    checks[-1].update(
        provider=target_provider,
        count=len(target_evaluation["items"]),
        guard=target_evaluation["status"],
        retried=target_result["semantic_retry_used"],
    )

    submittable_result = await measured(
        "resume_submittable",
        generate_guarded_resume(
            facts, job, targets, kind="submittable", contact=contact
        ),
        checks,
    )
    submittable_provider = submittable_result["provider"]
    submittable_evaluation = submittable_result["evaluation"]
    require(
        submittable_provider == "compatible", "resume_submittable 触发了 Provider 回退"
    )
    require(
        submittable_result["fallback_used"] is False,
        "resume_submittable 使用了本地内容回退",
    )
    require(
        submittable_evaluation["status"] == "passed",
        f"resume_submittable 未通过本地 Fact Guard：{submittable_evaluation['issues'][:5]}",
    )
    require(
        submittable_evaluation["unachieved_count"] == 0,
        "resume_submittable 包含未达成目标",
    )
    checks[-1].update(
        provider=submittable_provider,
        count=len(submittable_evaluation["items"]),
        guard=submittable_evaluation["status"],
        retried=submittable_result["semantic_retry_used"],
    )

    expected_unachieved = target_evaluation["unachieved_count"]
    interview_content = await measured(
        "interview_guide",
        generate_guarded_interview(
            job,
            target_content,
            facts,
            targets,
            expected_unachieved_count=expected_unachieved,
        ),
        checks,
    )
    require(
        interview_content["provider"] == "compatible",
        "interview_guide 触发了 Provider 回退",
    )
    require(
        interview_content["fallback_used"] is False,
        f"interview_guide 使用了本地回退：{interview_content['model_validation_issues'][:5]}",
    )
    require(
        interview_content["guide_guard_status"] == "passed",
        f"interview_guide 未通过本地安全检查：{interview_content['guide_guard_issues'][:5]}",
    )
    checks[-1].update(
        provider=interview_content["provider"],
        count=len(interview_content["questions"]),
        guard=interview_content["guide_guard_status"],
        retried=interview_content["semantic_retry_used"],
        grounded=interview_content["deterministic_grounding_used"],
    )

    email_result = await measured(
        "email_draft",
        build_email_draft(
            SimpleNamespace(school="虚构大学", major="工程专业"),
            SimpleNamespace(
                kind="target",
                unachieved_count=expected_unachieved,
                title=f"{job.company_name} - {job.title}",
            ),
            job,
            SimpleNamespace(company_name=job.company_name, email="jobs@example.test"),
            facts=facts,
            contact=contact,
        ),
        checks,
    )
    require(
        email_result["provider"] == "compatible", "email_draft 触发了 Provider 回退"
    )
    require(email_result["fallback_used"] is False, "email_draft 触发了语义回退")
    require(email_result["guard_status"] == "passed", "email_draft 未通过本地安全检查")
    checks[-1].update(
        provider=email_result["provider"],
        count=len(email_result["match_points"]),
        guard=email_result["guard_status"],
    )
    return {
        "case": case.name,
        "status": "passed",
        "configuration": {
            "cheap_model": settings.model_for("resume_extract"),
            "strong_model": settings.model_for("resume_rewrite"),
            "thinking": settings.llm_thinking_enabled,
            "reasoning_effort": settings.llm_reasoning_effort,
        },
        "checks": checks,
    }


async def run_interview_only(case: SyntheticCase) -> dict:
    settings = get_settings()
    checks: list[dict] = []
    facts = make_facts(case)
    job = make_job(case)
    target = SimpleNamespace(
        id="target-interview-only",
        requirement=case.gap["requirement"],
        category=case.gap["category"],
        severity=case.gap["severity"],
        deliverable=f"完成{case.gap['requirement']}学习记录",
        acceptance_criteria_json=["产出物可以查看", "过程记录可核对"],
        status="pending",
        achieved_fact_id=None,
    )
    target_content = generate_resume(
        facts,
        job,
        [target],
        kind="target",
        contact={"name": "测试用户", "email": "tester@example.test", "city": job.city},
    )
    interview_content = await measured(
        "interview_guide",
        generate_guarded_interview(
            job,
            target_content,
            facts,
            [target],
            expected_unachieved_count=1,
        ),
        checks,
    )
    require(
        interview_content["provider"] == "compatible",
        "interview_guide 触发了 Provider 回退",
    )
    require(
        interview_content["fallback_used"] is False, "interview_guide 使用了本地回退"
    )
    require(
        interview_content["guide_guard_status"] == "passed",
        f"interview_guide 未通过本地安全检查：{interview_content['guide_guard_issues'][:5]}",
    )
    checks[-1].update(
        provider=interview_content["provider"],
        count=len(interview_content["questions"]),
        guard=interview_content["guide_guard_status"],
        retried=interview_content["semantic_retry_used"],
        grounded=interview_content["deterministic_grounding_used"],
    )
    return {
        "case": case.name,
        "status": "passed",
        "configuration": {
            "strong_model": settings.model_for("interview_guide"),
            "thinking": settings.llm_thinking_enabled,
            "reasoning_effort": settings.llm_reasoning_effort,
            "timeout_seconds": settings.llm_timeout_seconds,
            "max_output_tokens": settings.llm_max_output_tokens,
        },
        "checks": checks,
    }


async def run_email_only(case: SyntheticCase) -> dict:
    settings = get_settings()
    checks: list[dict] = []
    facts = make_facts(case)
    job = make_job(case)
    email_result = await measured(
        "email_draft",
        build_email_draft(
            SimpleNamespace(school="虚构大学", major="工程专业"),
            SimpleNamespace(
                kind="target",
                unachieved_count=1,
                title=f"{job.company_name} - {job.title}",
            ),
            job,
            SimpleNamespace(company_name=job.company_name, email="jobs@example.test"),
            facts=facts,
            contact={
                "name": "测试用户",
                "phone": "",
                "email": "tester@example.test",
                "city": job.city,
            },
        ),
        checks,
    )
    require(
        email_result["provider"] == "compatible", "email_draft 触发了 Provider 回退"
    )
    require(email_result["fallback_used"] is False, "email_draft 使用了本地回退")
    require(email_result["guard_status"] == "passed", "email_draft 未通过本地安全检查")
    checks[-1].update(
        provider=email_result["provider"],
        count=len(email_result["match_points"]),
        guard=email_result["guard_status"],
    )
    return {
        "case": case.name,
        "status": "passed",
        "configuration": {
            "cheap_model": settings.model_for("email_draft"),
            "thinking": settings.llm_thinking_enabled,
            "reasoning_effort": settings.llm_reasoning_effort,
            "timeout_seconds": settings.llm_timeout_seconds,
            "max_output_tokens": settings.llm_max_output_tokens,
        },
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用虚构数据执行一次真实 LLM 安全回归")
    parser.add_argument("--case", choices=sorted(CASES), required=True)
    parser.add_argument(
        "--only",
        choices=("all", "interview_guide", "email_draft"),
        default="all",
        help="只重测指定的高成本任务；默认执行完整回归",
    )
    parser.add_argument(
        "--verbose-metadata",
        action="store_true",
        help="输出不含 Prompt、正文或密钥的 Provider 运行元数据",
    )
    parser.add_argument(
        "--acknowledge-cost",
        action="store_true",
        help="确认本次会调用已配置的付费 LLM Provider",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.acknowledge_cost:
        print("拒绝执行：请显式添加 --acknowledge-cost。", file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.llm_provider.strip().lower() != "compatible":
        print("拒绝执行：LLM_PROVIDER 必须为 compatible。", file=sys.stderr)
        return 2
    if not settings.llm_api_key.get_secret_value() or not settings.model_for("resume_rewrite"):
        print("拒绝执行：真实 Provider 配置不完整。", file=sys.stderr)
        return 2
    if args.verbose_metadata:
        logger = logging.getLogger("app.llm")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    try:
        operation = {
            "all": run_case,
            "interview_guide": run_interview_only,
            "email_draft": run_email_only,
        }[args.only]
        result = asyncio.run(operation(CASES[args.case]))
    except SmokeFailure as exc:
        print(
            json.dumps(
                {"case": args.case, "status": "failed", "reason": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
