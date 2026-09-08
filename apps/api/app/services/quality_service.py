"""Deterministic hard gates plus optional model critic scores."""

from __future__ import annotations

from app.providers.llm.base import ProviderError
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import QualityCriticOutput
from app.services.content_contract import iter_bullets, visible_bullets
from app.services.fact_guard import guard_content
from app.services.resume_generator import estimate_resume_lines
from app.services.resume_template import SECTION_ORDER

QUALITY_DIMENSIONS = (
    "target_relevance",
    "specificity",
    "personal_contribution",
    "information_density",
    "readability",
    "ats",
    "interview_defensibility",
)


def report_guard_passed(report: dict) -> bool:
    """Return the independent provenance result from a quality report.

    ``hard_passed`` intentionally combines provenance, semantic and layout
    checks for the normal delivery gate. The local debug switch may bypass
    the latter, but it must never bypass invalid source IDs or other Fact
    Guard failures.
    """
    return (report.get("guard") or {}).get("status") == "passed"


def quality_report_status(report: dict, *, gate_enabled: bool) -> str:
    """Map a report to a user-visible delivery status."""
    if not report_guard_passed(report):
        return "blocked"
    if report.get("hard_passed") is True:
        return "passed"
    return "blocked" if gate_enabled else "bypassed"


def evaluate_version(
    *,
    content: dict,
    facts: list,
    requirements: list[dict],
    mode: str,
    expected_headline: str = "",
) -> dict:
    requirement_targets = [
        _RequirementTarget(item) for item in requirements if item.get("id")
    ]
    guard = guard_content(content, facts, requirement_targets, mode=mode)
    if content.get("factuality_policy") == "ai_expansion":
        guard = _expansion_guard(content, facts, requirements, guard)
    hard_issues = list(guard["issues"])
    hard_issues.extend(_kind_issues(content, mode))
    hard_issues.extend(_coverage_issues(content, requirements, mode))
    hard_issues.extend(_structure_issues(content))
    layout_warnings = _layout_warnings(content)
    if expected_headline and expected_headline not in str(content.get("headline") or ""):
        # Headline may be specialized around the job title; only flag empty.
        pass
    if not str(content.get("headline") or "").strip():
        hard_issues.append("缺少求职方向")

    scores = _explanatory_scores(content, requirements, mode)
    coverage = _uncovered_requirements(content, requirements, mode)
    hard_passed = not hard_issues
    status = "passed" if hard_passed else "blocked"
    return {
        "status": status,
        "hard_passed": hard_passed,
        "issues": hard_issues,
        "layout_warnings": layout_warnings,
        "uncovered_requirements": coverage,
        "dimensions": scores,
        "guard": guard,
        "unachieved_count": guard.get("unachieved_count") or 0,
        "content_version": content.get("content_version"),
        "reviewer": "deterministic",
        "reviewer_note": "使用确定性检查",
        "warnings": list(guard.get("warnings") or []) + [
            {"bullet_id": "", "message": warning} for warning in layout_warnings
        ],
    }


async def evaluate_version_with_critic(
    *,
    content: dict,
    facts: list,
    requirements: list[dict],
    mode: str,
) -> dict:
    report = evaluate_version(
        content=content, facts=facts, requirements=requirements, mode=mode
    )
    mock = {
        "dimensions": {
            name: {"score": int(report["dimensions"][name]["score"]), "notes": []}
            for name in QUALITY_DIMENSIONS
            if name in report["dimensions"]
        },
        "summary": "确定性检查结果",
    }
    try:
        critic, provider = await generate_structured(
            task="resume_quality",
            system_prompt=(
                "你是简历质量评审。根据简历正文、素材和目标要求评价表达与岗位相关性。"
                "当 factuality_policy=ai_expansion 时允许 AI 补充，缺少事实支持只作提示，不阻止交付。"
                "输出严格 JSON。"
            ),
            user_payload={
                "content": content,
                "facts": [{"id": fact.id, "text": (fact.value_json or {}).get("text") or fact.source_text} for fact in facts],
                "requirements": requirements,
                "kind": mode,
                "headline": content.get("headline"),
                "bullet_count": len(visible_bullets(content)),
                "hard_passed": report["hard_passed"],
                "mock_response": mock,
            },
            response_model=QualityCriticOutput,
        )
        dimensions = {}
        for name in QUALITY_DIMENSIONS:
            item = critic.dimensions.get(name)
            if item is None:
                dimensions[name] = report["dimensions"].get(name) or {"score": 60, "notes": []}
            else:
                dimensions[name] = {"score": item.score, "notes": list(item.notes or [])}
        report["dimensions"] = dimensions
        report["reviewer"] = "model" if provider == "compatible" else "deterministic"
        report["reviewer_note"] = f"模型评审（{provider}）" if provider == "compatible" else "使用确定性检查"
        report["critic_summary"] = critic.summary
    except (ProviderError, Exception):
        report["reviewer"] = "deterministic"
        report["reviewer_note"] = "模型不可用，使用确定性检查"
        report["critic_unavailable"] = True
    if not report.get("hard_passed"):
        report["status"] = "blocked"
    return report


def apply_critic_cannot_override(report: dict, critic_score: float | None = None) -> dict:
    report = dict(report)
    if critic_score is not None:
        report["critic_score"] = critic_score
    if not report.get("hard_passed"):
        report["status"] = "blocked"
    return report


def _kind_issues(content: dict, mode: str) -> list[str]:
    issues = []
    if content.get("kind") != mode:
        issues.append("简历 kind 与生成模式不一致")
    for _section, _item, bullet in iter_bullets(content):
        if content.get("factuality_policy") == "ai_expansion":
            continue
        if mode == "submittable" and bullet.get("achieved") is False:
            issues.append("真实能力简历不得包含未达成要点")
        if mode == "submittable" and (
            bullet.get("source_target_ids") or bullet.get("requirement_ids")
        ):
            issues.append("真实能力简历不得引用未达成目标")
        if (
            mode == "target"
            and bullet.get("achieved") is False
            and not (bullet.get("requirement_ids") or bullet.get("source_target_ids"))
        ):
            issues.append("未达成要点缺少目标要求来源")
    return list(dict.fromkeys(issues))


def _expansion_guard(content: dict, facts: list, requirements: list[dict], strict: dict) -> dict:
    """Use fact checks as provenance diagnostics, not a delivery veto."""
    fact_ids = {str(fact.id) for fact in facts}
    req_ids = {str(req["id"]) for req in requirements if req.get("id")}
    issues = []
    warnings = []
    for (_section, item, bullet), result in zip(iter_bullets(content), strict["items"]):
        cited_facts = set(bullet.get("source_fact_ids") or [])
        cited_targets = set((bullet.get("source_target_ids") or []) + (bullet.get("requirement_ids") or []))
        invalid = bool(cited_facts - fact_ids or cited_targets - req_ids)
        if invalid:
            issues.append("引用了不属于当前生成上下文的来源")
        # Also cover generated entry headers; the legacy guard only checks bullet text.
        cited = [fact for fact in facts if str(fact.id) in cited_facts]
        header_added = any(
            item.get(field) and not any(str(getattr(fact, field, "") or "") == str(item[field]) for fact in cited)
            for field in ("organization", "role_title", "location", "start_date", "end_date")
        )
        unverified = bool(result["issues"] or not cited_facts or header_added or bullet.get("verification_status") == "ai_generated")
        if unverified:
            bullet["verification_status"] = "ai_generated"
            bullet["achieved"] = False
            warnings.append({"bullet_id": bullet["id"], "message": "AI 扩写内容，未绑定用户事实来源"})
        else:
            bullet["verification_status"] = "source_based"
        result.update(status="blocked" if invalid else "passed", achieved=bullet.get("achieved"), verification_status=bullet["verification_status"])
    if not strict["items"]:
        issues.append("简历内容没有可校验条目")
    return {**strict, "status": "blocked" if issues else "passed", "issues": sorted(set(issues)), "warnings": warnings,
            "unachieved_count": sum(b.get("achieved") is False for b in visible_bullets(content))}


def _coverage_issues(content: dict, requirements: list[dict], mode: str) -> list[str]:
    uncovered = _uncovered_requirements(content, requirements, mode)
    high = [item for item in uncovered if item.get("priority") == "high"]
    if mode == "target" and high:
        return ["蓝图未覆盖高优先级目标要求"]
    return []


def _uncovered_requirements(content: dict, requirements: list[dict], mode: str) -> list[dict]:
    cited: set[str] = set()
    fact_text = " ".join(
        str(bullet.get("text") or "") for bullet in visible_bullets(content)
    )
    for _section, _item, bullet in iter_bullets(content):
        cited.update(str(item) for item in bullet.get("requirement_ids") or [])
        cited.update(str(item) for item in bullet.get("source_target_ids") or [])
    missing = []
    for item in requirements:
        if item.get("priority") != "high":
            continue
        req_id = str(item.get("id") or "")
        text = str(item.get("text") or "")
        if req_id in cited:
            continue
        if mode == "submittable" and text and text in fact_text:
            continue
        missing.append(
            {
                "id": req_id,
                "text": text,
                "priority": item.get("priority"),
                "covered_in": None,
            }
        )
    return missing


def _structure_issues(content: dict) -> list[str]:
    names = [
        str(section.get("name") or "")
        for section in content.get("sections") or []
        if section.get("items")
    ]
    ordered = [name for name in SECTION_ORDER if name in names]
    actual = [name for name in names if name in SECTION_ORDER]
    if ordered != actual:
        return ["分区顺序不符合模板"]
    return []


def _layout_warnings(content: dict) -> list[str]:
    if estimate_resume_lines(content) > 48:
        return ["超过单页内容预算"]
    return []


def _explanatory_scores(content: dict, requirements: list[dict], mode: str) -> dict:
    bullets = visible_bullets(content)
    density = min(100, 40 + 8 * len(bullets))
    coverage = 100
    high = [item for item in requirements if item.get("priority") == "high"]
    if high:
        missing = _uncovered_requirements(content, requirements, mode)
        coverage = int(round(100 * (1 - len(missing) / max(len(high), 1))))
    personal = 80 if any("本人" in str(b.get("text")) or b.get("source_fact_ids") for b in bullets) else 55
    scores = {
        "target_relevance": coverage,
        "specificity": 70 if any(ch.isdigit() for b in bullets for ch in b.get("text", "")) else 60,
        "personal_contribution": personal,
        "information_density": density,
        "readability": 75,
        "ats": 80,
        "interview_defensibility": 70 if mode == "submittable" else 65,
    }
    return {
        name: {"score": scores[name], "notes": []}
        for name in QUALITY_DIMENSIONS
    }


class _RequirementTarget:
    def __init__(self, item: dict):
        self.id = item.get("id")
        self.status = "pending"
        self.deliverable = item.get("text") or ""
        self.acceptance_criteria_json = [
            source.get("evidence") or ""
            for source in item.get("sources") or []
        ]
        self.requirement = item.get("text") or ""
