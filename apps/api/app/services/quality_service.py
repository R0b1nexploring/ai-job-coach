"""Deterministic hard gates plus optional model critic scores."""

from __future__ import annotations

import re
import unicodedata

from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import QualityCriticOutput
from app.services.content_contract import (
    has_star_contract,
    is_project_item,
    iter_bullets,
    iter_project_stories,
    visible_bullets,
)
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

# Critic completeness. A partial critique keeps its usable findings but must
# never be reported as a clean review.
CRITIC_COMPLETE = "complete"
CRITIC_PARTIAL = "partial"
CRITIC_UNAVAILABLE = "unavailable"

# Semantic content problems the critic may locate. Only these trigger the
# background targeted repair contract; style or low scores never do.
SEMANTIC_ISSUE_CODES = frozenset(
    {
        "star_missing",
        "plan_contradiction",
        "action_result_mismatch",
    }
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
    hard_issues.extend(_project_star_issues(content, mode))
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
        # Local checks never stand in for a semantic review. Reporting the
        # critic as unavailable here prevents "no local issue" from being read
        # as "semantically verified".
        "critic_status": CRITIC_UNAVAILABLE,
        "critic_unavailable": True,
        "critic_missing_dimensions": list(QUALITY_DIMENSIONS),
        "semantic_issues": [],
        "warnings": list(guard.get("warnings") or []) + [
            {"bullet_id": "", "message": warning} for warning in layout_warnings
        ],
        "star_diagnostics": _project_star_diagnostics(content, mode),
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
        "recommendations": [],
        "project_reviews": [],
    }
    try:
        critic, provider = await generate_structured(
            task="resume_quality",
            system_prompt=(
                "你是简历质量评审。根据简历正文、素材和目标要求评价表达与岗位相关性。"
                "当 factuality_policy=ai_expansion 时允许 AI 补充，缺少事实支持只作提示，不阻止交付。"
                "必须评价全部质量维度；对可改进的具体要点给出带 bullet_id 的、可执行的修改建议。"
                "如存在 project_story，逐项评价背景/任务/行动/结果是否具体、行动是否能支撑结果、"
                "个人贡献和技术取舍是否可追问，并用 project_id 和关联 bullet_ids 定位问题。"
                "蓝图（kind=target）项目按设计即为未来计划：achieved=false、结果为预期交付物、"
                "指标 kind=target，这属于正常状态，绝不算作矛盾或缺项；不要因为项目尚未完成、"
                "或正文使用“计划”措辞而判定计划与正文矛盾。"
                "只有在同一要点内部存在实质冲突时才填 issue_code："
                "star_missing（必需要素确实缺失或只有空话）、"
                "plan_contradiction（正文与已保存方案描述不一致）、"
                "action_result_mismatch（所述行动在方法上无法支撑所声称的结果）。"
                "仅是建议改进、措辞、时态、数值锚点不足或风格偏好时，issue_code 必须留空，"
                "把建议写进 suggestions；不要用 issue_code 表达改进意见。"
                "输出严格 JSON。"
            ),
            user_payload={
                "content": content,
                "facts": [{"id": fact.id, "text": (fact.value_json or {}).get("text") or fact.source_text} for fact in facts],
                "requirements": requirements,
                "kind": mode,
                "headline": content.get("headline"),
                "bullet_count": len(visible_bullets(content)),
                "bullets": [
                    {"id": bullet.get("id"), "text": bullet.get("text")}
                    for bullet in visible_bullets(content)
                ],
                "project_stories": [
                    {
                        "project_id": story.get("project_id"),
                        "title": story.get("title"),
                        "bullet_ids": story.get("bullet_ids") or [],
                        "situation": story.get("situation") or {},
                        "task": story.get("task") or {},
                        "actions": story.get("actions") or [],
                        "result": story.get("result") or {},
                    }
                    for _section, _item, story in iter_project_stories(content)
                ],
                "hard_passed": report["hard_passed"],
                "star_diagnostics": report["star_diagnostics"],
                "mock_response": mock,
            },
            response_model=QualityCriticOutput,
        )
        dimensions = {}
        for name in QUALITY_DIMENSIONS:
            item = critic.dimensions.get(name)
            if item is None:
                dimensions[name] = {
                    "score": None,
                    "notes": ["模型未评估此维度"],
                    "assessed": False,
                }
            else:
                dimensions[name] = {"score": item.score, "notes": list(item.notes or []), "assessed": True}
        report["dimensions"] = dimensions
        report["reviewer"] = "model" if provider == "compatible" else "deterministic"
        report["reviewer_note"] = (
            f"模型评审（{provider}）"
            if provider == "compatible"
            else "模型不可用或未配置，使用确定性检查"
        )
        report["critic_summary"] = critic.summary
        report["critic_unavailable"] = provider != "compatible"
        # A critique counts as complete only when the model assessed every
        # required dimension. Anything less keeps its usable findings but is
        # recorded as partial, so a missing dimension is never read as
        # "no problem found".
        missing_dimensions = [
            name for name, item in dimensions.items() if not item.get("assessed")
        ]
        report["critic_missing_dimensions"] = missing_dimensions
        if provider != "compatible":
            report["critic_status"] = CRITIC_UNAVAILABLE
        elif missing_dimensions:
            report["critic_status"] = CRITIC_PARTIAL
        else:
            report["critic_status"] = CRITIC_COMPLETE
        valid_bullet_ids = {str(bullet.get("id") or "") for bullet in visible_bullets(content)}
        valid_project_ids = {
            str(story.get("project_id") or "")
            for _section, _item, story in iter_project_stories(content)
        }
        report["recommendations"] = [
            {
                "bullet_id": item.bullet_id,
                "project_id": item.project_id,
                "suggestion": item.suggestion,
            }
            for item in critic.recommendations
            if (not item.bullet_id or item.bullet_id in valid_bullet_ids)
            and (not item.project_id or item.project_id in valid_project_ids)
        ]
        report["project_reviews"] = [
            {
                "project_id": item.project_id,
                "bullet_ids": [bullet_id for bullet_id in item.bullet_ids if bullet_id in valid_bullet_ids],
                "diagnosis": item.diagnosis,
                "suggestions": list(item.suggestions or []),
                "issue_code": item.issue_code,
            }
            for item in critic.project_reviews
            if item.project_id in valid_project_ids
        ]
        report["semantic_issues"] = _semantic_issues(report["project_reviews"])
    except Exception:
        report["reviewer"] = "deterministic"
        report["reviewer_note"] = "模型不可用，使用确定性检查"
        report["critic_unavailable"] = True
        report["critic_status"] = CRITIC_UNAVAILABLE
        report["critic_missing_dimensions"] = list(QUALITY_DIMENSIONS)
        report["recommendations"] = []
        report["project_reviews"] = []
        report["semantic_issues"] = []
    if not report.get("hard_passed"):
        report["status"] = "blocked"
    return report


def _semantic_issues(project_reviews: list[dict]) -> list[dict]:
    """Extract the critic findings that justify a targeted background repair.

    The critic must point at a concrete project and bullet with a diagnosis and
    a recognised issue code. An unclassified diagnosis stays explanatory only,
    which keeps low scores and style preferences out of the repair loop.
    """
    issues = []
    for review in project_reviews or []:
        if not isinstance(review, dict):
            continue
        code = str(review.get("issue_code") or "").strip()
        if code not in SEMANTIC_ISSUE_CODES:
            continue
        project_id = str(review.get("project_id") or "")
        bullet_ids = [str(value) for value in review.get("bullet_ids") or [] if str(value)]
        diagnosis = str(review.get("diagnosis") or "").strip()
        if not project_id or not bullet_ids or not diagnosis:
            continue
        issues.append(
            {
                "code": code,
                "project_id": project_id,
                "bullet_ids": bullet_ids,
                "diagnosis": diagnosis,
                "suggestions": list(review.get("suggestions") or []),
            }
        )
    return issues


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


_VAGUE_STAR_VALUES = frozenset({"负责相关工作", "完成项目", "提升效果", "取得成果", "若干", "相关内容"})


def _project_star_issues(content: dict, mode: str) -> list[str]:
    """Hard-check locally owned STAR shape and provenance for new blueprints."""
    if mode != "target" or not has_star_contract(content):
        return []
    issues: list[str] = []
    for section in content.get("sections") or []:
        for item in section.get("items") or []:
            if not is_project_item(section, item):
                continue
            story = item.get("project_story")
            label = str((story or {}).get("project_id") or item.get("organization") or item.get("role_title") or "项目")
            if not isinstance(story, dict):
                issues.append(f"项目 {label} 缺少完整 STAR 故事")
                continue
            if int(story.get("schema_version") or 0) != 1:
                issues.append(f"项目 {label} 的 STAR 版本无效")
            situation = story.get("situation") or {}
            task = story.get("task") or {}
            result = story.get("result") or {}
            # Known filler must fail here, not merely appear in diagnostics: a
            # placeholder project is not a deliverable STAR story, even when
            # every field is technically non-empty.
            if not _has_project_detail(situation.get("context")) or not _has_project_detail(
                situation.get("problem")
            ):
                issues.append(f"项目 {label} 的 S（背景/问题）不具体")
            if not _has_project_detail(task.get("role")) or not _has_project_detail(
                task.get("goal")
            ):
                issues.append(f"项目 {label} 的 T（角色/目标）不具体")
            actions = story.get("actions") or []
            if not isinstance(actions, list) or not actions or not all(
                isinstance(action, dict)
                and _has_project_detail(action.get("step"))
                and _has_project_detail(action.get("method"))
                and _has_project_detail(action.get("contribution"))
                for action in actions
            ):
                issues.append(f"项目 {label} 的 A（行动/方法/贡献）不完整")
            deliverables = result.get("deliverables") or []
            if not _specific_star_values(deliverables) or not _has_project_detail(
                result.get("verification_method")
            ):
                issues.append(f"项目 {label} 的 R（交付/验证）不完整")
            bullets = [bullet for bullet in item.get("bullets") or [] if isinstance(bullet, dict)]
            bullet_ids = [str(bullet.get("id") or "") for bullet in bullets if bullet.get("id")]
            story_bullet_ids = [str(value) for value in story.get("bullet_ids") or [] if str(value)]
            if bullet_ids != story_bullet_ids:
                issues.append(f"项目 {label} 的 STAR 要点映射不一致")
            fact_ids = _ordered_refs(bullet.get("source_fact_ids") or [] for bullet in bullets)
            target_ids = _ordered_refs(bullet.get("source_target_ids") or [] for bullet in bullets)
            requirement_ids = _ordered_refs(
                (bullet.get("requirement_ids") or bullet.get("source_target_ids") or [])
                for bullet in bullets
            )
            if list(story.get("source_fact_ids") or []) != fact_ids:
                issues.append(f"项目 {label} 的事实来源映射不一致")
            if list(story.get("source_target_ids") or []) != target_ids:
                issues.append(f"项目 {label} 的目标来源映射不一致")
            if list(story.get("requirement_ids") or []) != requirement_ids:
                issues.append(f"项目 {label} 的岗位要求映射不一致")
            if story.get("achieved") is False:
                for metric in result.get("metrics") or []:
                    if isinstance(metric, dict) and metric.get("kind") == "observed":
                        issues.append(f"项目 {label} 的未达成结果不能标为已观察指标")
    return list(dict.fromkeys(issues))


_STAR_PLACEHOLDERS = _VAGUE_STAR_VALUES | frozenset({
    "业务需要", "效果不好", "负责开发", "使用工具", "效果良好",
    "围绕目标岗位设计一段可验证的项目实践",
    "需要把岗位要求转为可拆分、可验证的项目产出",
    "需要在既有项目约束下完成可复盘的交付",
    "形成可演示、可复盘的项目交付",
    "先定义输入、输出和验证方式，再按阶段保留过程记录",
    "说明该方法如何服务项目目标", "明确约束、风险与取舍",
    "让每个行动都能追溯到岗位要求和最终交付",
    "在时间、素材与技术边界内做取舍",
    "本人负责的已确认部分", "计划负责方案拆解、执行记录与验证",
    "可演示的项目产出", "过程记录与版本说明",
    "用交付物、过程记录和验收条件逐项核验",
    "记录测量口径、环境与验收条件",
})


# Shortest value that can still name a concrete role, goal or method. Shorter
# labels ("成员", "建模") cannot be distinguished from filler.
_MIN_PROJECT_DETAIL_LENGTH = 4


def _has_project_detail(value: object) -> bool:
    text = str(value or "").strip().rstrip("。.!！;；")
    # A two- or three-character label ("成员", "建模") is not a project role or
    # goal; it cannot be told apart from filler, so it fails the detail check.
    return (
        len(text) >= _MIN_PROJECT_DETAIL_LENGTH
        and text not in _STAR_PLACEHOLDERS
    )


def _project_star_diagnostics(content: dict, mode: str) -> list[dict]:
    """Locate missing details and known filler, not certify technical validity.

    These remain advisory: a local fallback can pass structural gates while
    explicitly exposing the project details that still need to be developed.
    """
    if mode != "target" or not has_star_contract(content):
        return []
    diagnostics = []
    for _section, item, story in iter_project_stories(content):
        def check(value: object, field: str, message: str) -> None:
            if not _has_project_detail(value):
                diagnostics.append(_diagnostic(story, field, message, item=item))

        situation = story.get("situation") or {}
        task = story.get("task") or {}
        actions = story.get("actions") or []
        result = story.get("result") or {}
        check(situation.get("context"), "situation.context", "背景缺少具体使用场景或处理对象")
        check(situation.get("problem"), "situation.problem", "问题描述缺少需要解决的具体障碍")
        check(task.get("goal"), "task.goal", "个人目标缺少明确的任务或产出")
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                continue  # Invalid structure is reported by the hard gate.
            for field, message in (
                ("step", "行动缺少具体操作步骤"),
                ("method", "行动缺少操作对象和具体方法"),
                ("contribution", "行动缺少个人承担的具体工作"),
                ("rationale", "行动缺少为什么这样做的取舍说明"),
                ("difficulty", "行动缺少可追问的难点或风险"),
            ):
                check(action.get(field), f"actions.{index}.{field}", message)
        if not any(_has_project_detail(value) for value in result.get("deliverables") or []):
            check(None, "result.deliverables", "结果缺少可检查的具体交付物")
        check(result.get("verification_method"), "result.verification_method", "结果缺少具体检查步骤或比较方法")
        for index, metric in enumerate(result.get("metrics") or []):
            if isinstance(metric, dict):
                check(metric.get("conditions"), f"result.metrics.{index}.conditions", "结果指标缺少测量口径或验收条件")
        diagnostics.extend(_visible_coverage_diagnostics(story, item=item))
    return diagnostics


def _diagnostic(story: dict, field: str, message: str, *, item: dict | None = None) -> dict:
    bullet_ids = story.get("bullet_ids")
    if not bullet_ids and item is not None:
        bullet_ids = [
            bullet.get("id")
            for bullet in item.get("bullets") or []
            if isinstance(bullet, dict) and bullet.get("id")
        ]
    return {
        "project_id": story.get("project_id"),
        "bullet_ids": list(bullet_ids or []),
        "field": field,
        "message": message,
    }


_STAR_COVERAGE_STOP_TOKENS = frozenset(
    {"负责", "要求", "相关", "岗位", "工作", "能够", "以及", "进行", "完成", "说明", "使用", "项目", "目标", "形成"}
)


def _coverage_tokens(value: object) -> set[str]:
    """Coarse deterministic tokens used only to locate dropped STAR elements.

    No embedding or model call: the same saved content always yields the same
    coverage verdict, and a zero-overlap result is a prompt to review rather
    than a sentence-level semantic proof.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens = set(re.findall(r"[a-z][a-z0-9+.#/-]{1,}|[\u4e00-\u9fff]{2,}", text))
    for fragment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        tokens.update(fragment[index : index + 2] for index in range(len(fragment) - 1))
    return {token for token in tokens if token not in _STAR_COVERAGE_STOP_TOKENS}


def _visible_coverage_diagnostics(story: dict, *, item: dict) -> list[dict]:
    """Flag plan elements whose vocabulary never reaches the visible bullets.

    The mapping in ``bullet_ids`` only proves that bullets exist for a project;
    it does not prove the compressed copy still says what the plan intended.
    We therefore compare a conservative token set per element group and report
    the group when a concrete plan element has no overlap at all with the
    visible text.  This is advisory and never triggers an automatic rewrite.
    """
    bullets = [bullet for bullet in item.get("bullets") or [] if isinstance(bullet, dict)]
    if not bullets:
        return []
    bullet_tokens: set[str] = set()
    for bullet in bullets:
        bullet_tokens |= _coverage_tokens(bullet.get("text"))
    if not bullet_tokens:
        return []
    situation = story.get("situation") or {}
    task = story.get("task") or {}
    actions = story.get("actions") or []
    result = story.get("result") or {}
    groups = (
        ("visible_coverage.situation", "可见正文没有保留项目背景或问题", [situation.get("context"), situation.get("problem")]),
        ("visible_coverage.task", "可见正文没有保留本人的任务或目标", [task.get("goal")]),
        (
            "visible_coverage.result",
            "可见正文没有保留项目结果或验证方式",
            [result.get("verification_method"), *(result.get("deliverables") or [])],
        ),
    )
    diagnostics = []
    for field, message, values in groups:
        plan_tokens: set[str] = set()
        for value in values:
            if _has_project_detail(value):
                plan_tokens |= _coverage_tokens(value)
        if plan_tokens and not (plan_tokens & bullet_tokens):
            diagnostics.append(_diagnostic(story, field, message, item=item))
    return diagnostics


def _ordered_refs(rows) -> list[str]:
    values = []
    for row in rows:
        for value in row or []:
            text = str(value or "")
            if text and text not in values:
                values.append(text)
    return values


def _specific_star_text(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) >= 4 and text not in _VAGUE_STAR_VALUES


def _specific_star_values(values: object) -> bool:
    return isinstance(values, list) and any(_specific_star_text(value) for value in values)


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
