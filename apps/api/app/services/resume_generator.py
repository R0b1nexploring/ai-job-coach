import math
import re
from copy import deepcopy

from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import ResumeStructuredV2Output

from .fact_guard import guard_content

MAX_BULLET_CHARS = 45
MAX_RESUME_LINES = 48
ACTION_PREFIXES = (
    "负责",
    "完成",
    "使用",
    "参与",
    "主导",
    "协助",
    "设计",
    "开发",
    "维护",
    "编制",
    "优化",
    "搭建",
    "分析",
    "验证",
    "实现",
    "制作",
    "组织",
    "推进",
    "支持",
    "学习",
    "掌握",
    "输出",
    "具备",
    "积累",
    "围绕",
)
CATEGORY_ORDER = {
    "employment": 0,
    "projects": 1,
    "skills": 2,
    "education": 3,
    "certificates": 4,
    "other": 5,
}
SECTION_NAMES = {
    "employment": "工作与实习经历",
    "projects": "项目经历",
    "skills": "技能",
    "education": "教育背景",
    "certificates": "证书",
    "other": "其他经历",
}
DEFAULT_PREFIX = {
    "employment": "积累",
    "projects": "完成",
    "skills": "掌握",
    "education": "具备",
    "certificates": "具备",
    "other": "积累",
}
RESUME_SYSTEM_PROMPT = (
    "你是中文求职简历编辑。每个 bullet 必须引用 source_fact_ids 或 "
    "source_target_ids；不得引入来源中不存在的数字、工具、公司、证书，不得把团队"
    "成果写成个人成果。日期未知必须留空。每条不超过 45 字且以动作词开头，同一章节"
    "动作词不重复。kind=target 且输入含 capability_targets 时，必须至少选择一条目标，"
    "填写 source_target_ids 且 achieved 必须为 false。所有 new_claims 必须为空数组；"
    "无法完全溯源的 bullet 直接省略。请在一页预算内取舍，不要缩小字号。输出严格 JSON。"
)


def generate_resume(
    facts: list,
    job,
    targets: list | None = None,
    *,
    kind: str = "submittable",
    contact: dict | None = None,
) -> dict:
    confirmed = [fact for fact in facts if fact.verification_status == "user_confirmed"]
    active_targets = [
        target
        for target in targets or []
        if kind == "target" and getattr(target, "status", "pending") != "achieved"
    ]
    requirements = list(dict.fromkeys([*(job.must_have_json or []), *(job.keywords_json or [])]))
    fact_relevance = {str(fact.id): relevance(fact, requirements) for fact in confirmed}
    target_severity = {
        str(target.id): str(getattr(target, "severity", "medium")) for target in active_targets
    }
    grouped: dict[str, list[dict]] = {}
    for fact in sorted(
        confirmed,
        key=lambda item: (-fact_relevance[str(item.id)], CATEGORY_ORDER.get(item.category, 9)),
    ):
        grouped.setdefault(fact.category, []).append(_fact_item(fact))
    for target in sorted(
        active_targets,
        key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(item.severity, 1),
    ):
        category = target.category if target.category in SECTION_NAMES else "skills"
        grouped.setdefault(category, []).append(_target_item(target))

    content = {
        "content_version": 2,
        "kind": kind,
        "headline": job.title,
        "contact": dict(contact or {}),
        "sections": [
            {"name": SECTION_NAMES.get(category, "其他经历"), "items": items}
            for category, items in sorted(
                grouped.items(), key=lambda entry: CATEGORY_ORDER.get(entry[0], 9)
            )
        ],
        "excluded_gaps": [
            requirement
            for requirement in requirements
            if not any(requirement.casefold() in _fact_text(fact).casefold() for fact in confirmed)
        ],
    }
    content = enforce_page_budget(content, fact_relevance, target_severity)
    return _dedupe_section_verbs(content)


def evaluate_resume_content(
    content: dict,
    facts: list,
    targets: list | None,
    *,
    kind: str,
) -> dict:
    guard = guard_content(content, facts, targets, mode=kind)
    quality_issues = content_quality_issues(content, facts, targets, kind=kind)
    issues = sorted({*guard["issues"], *quality_issues})
    return {
        **guard,
        "status": "blocked" if issues else "passed",
        "issues": issues,
        "quality_issues": quality_issues,
    }


async def generate_guarded_resume(
    facts: list,
    job,
    targets: list | None = None,
    *,
    kind: str,
    contact: dict | None = None,
) -> dict:
    """Generate once, retry one semantic failure, then use the safe local result."""
    confirmed = [fact for fact in facts if fact.verification_status == "user_confirmed"]
    active_targets = list(targets or []) if kind == "target" else []
    fallback = generate_resume(confirmed, job, active_targets, kind=kind, contact=contact)
    payload = _resume_llm_payload(confirmed, job, active_targets, kind, contact, fallback)
    structured, provider_name = await generate_structured(
        task="resume_rewrite",
        system_prompt=RESUME_SYSTEM_PROMPT,
        user_payload=payload,
        response_model=ResumeStructuredV2Output,
    )
    content, evaluation = _prepare_and_evaluate_resume(
        structured.model_dump(), confirmed, job, active_targets, kind
    )
    semantic_retry_used = False
    semantic_retry_issues: list[str] = []
    if provider_name == "compatible" and evaluation["status"] == "blocked":
        semantic_retry_used = True
        semantic_retry_issues = list(evaluation["issues"][:10])
        retry_payload = {
            **payload,
            "previous_output_rejected": True,
            "validation_feedback": semantic_retry_issues,
        }
        structured, provider_name = await generate_structured(
            task="resume_rewrite",
            system_prompt=(
                f"{RESUME_SYSTEM_PROMPT}\n"
                "上一次结果未通过本地安全检查。请只依据 validation_feedback 修正规则问题；"
                "不要复述或猜测上一次正文，仍须生成完整 JSON。"
            ),
            user_payload=retry_payload,
            response_model=ResumeStructuredV2Output,
        )
        content, evaluation = _prepare_and_evaluate_resume(
            structured.model_dump(), confirmed, job, active_targets, kind
        )

    fallback_used = provider_name != "compatible"
    fallback_reason = ""
    if provider_name == "mock":
        fallback_reason = "configured_mock"
    elif provider_name == "mock_fallback":
        fallback_reason = "provider_error"
    model_validation_issues = (
        list(evaluation["issues"][:10]) if evaluation["status"] == "blocked" else []
    )
    if evaluation["status"] == "blocked":
        content = fallback
        fallback_used = True
        fallback_reason = "model_output_failed_validation"
        evaluation = evaluate_resume_content(content, confirmed, active_targets, kind=kind)
    return {
        "content": content,
        "provider": provider_name,
        "evaluation": evaluation,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "semantic_retry_used": semantic_retry_used,
        "semantic_retry_issues": semantic_retry_issues,
        "model_validation_issues": model_validation_issues,
    }


def _resume_llm_payload(
    facts: list,
    job,
    targets: list,
    kind: str,
    contact: dict | None,
    fallback: dict,
) -> dict:
    return {
        "confirmed_facts": [
            {
                "id": fact.id,
                "category": fact.category,
                "label": fact.label,
                "text": fact.value_json.get("text", ""),
                "organization": fact.organization,
                "role_title": fact.role_title,
                "location": fact.location,
                "start_date": fact.start_date,
                "end_date": fact.end_date,
                "provenance": fact.provenance,
            }
            for fact in facts
        ],
        "capability_targets": [
            {
                "id": target.id,
                "requirement": target.requirement,
                "category": target.category,
                "severity": target.severity,
                "deliverable": target.deliverable,
                "acceptance_criteria": target.acceptance_criteria_json,
            }
            for target in targets
        ],
        "job": {
            "title": job.title,
            "company_name": job.company_name,
            "must_have": job.must_have_json,
            "keywords": job.keywords_json,
        },
        "kind": kind,
        "output_requirements": {
            "minimum_target_bullets": 1 if targets else 0,
            "available_target_ids": [target.id for target in targets],
            "allowed_action_prefixes": list(ACTION_PREFIXES),
            "new_claims_must_be_empty": True,
            "instruction": (
                "蓝图不能只复述已确认事实；至少一条 bullet 必须逐字使用上述 target id；"
                "目标条目优先以“完成”或“学习”开头。所有 new_claims 必须是空数组。"
                if targets
                else "不得引用学习目标；所有 new_claims 必须是空数组。"
            ),
        },
        "contact": dict(contact or {}),
        "mock_response": fallback,
    }


def _prepare_and_evaluate_resume(
    content: dict,
    facts: list,
    job,
    targets: list,
    kind: str,
) -> tuple[dict, dict]:
    requirements = list(dict.fromkeys([*(job.must_have_json or []), *(job.keywords_json or [])]))
    fact_relevance = {str(fact.id): relevance(fact, requirements) for fact in facts}
    target_severity = {str(target.id): target.severity for target in targets}
    prepared = enforce_page_budget(content, fact_relevance, target_severity)
    evaluation = evaluate_resume_content(prepared, facts, targets, kind=kind)
    return prepared, evaluation


def content_quality_issues(
    content: dict,
    facts: list,
    targets: list | None,
    *,
    kind: str,
) -> list[str]:
    if content.get("content_version", 1) == 1:
        return []
    issues = []
    if content.get("kind") != kind:
        issues.append("简历 kind 与请求模式不一致")
    facts_by_id = {str(fact.id): fact for fact in facts}
    targets_by_id = {str(target.id): target for target in targets or []}
    referenced_target_ids: set[str] = set()
    for section_index, section in enumerate(content.get("sections") or []):
        verbs = set()
        for item_index, item in enumerate(section.get("items") or []):
            fact_ids = {
                str(value)
                for bullet in item.get("bullets") or []
                for value in bullet.get("source_fact_ids") or []
            }
            referenced_facts = [facts_by_id[value] for value in fact_ids if value in facts_by_id]
            for field in ("organization", "role_title", "location", "start_date", "end_date"):
                value = str(item.get(field) or "")
                if value and not any(
                    value == str(getattr(fact, field, "") or "") for fact in referenced_facts
                ):
                    issues.append(
                        f"第 {section_index + 1} 节第 {item_index + 1} 项的{field}缺少来源"
                    )
            for bullet_index, bullet in enumerate(item.get("bullets") or []):
                text = str(bullet.get("text") or "").strip()
                location = (
                    f"第 {section_index + 1} 节第 {item_index + 1} 项第 {bullet_index + 1} 条"
                )
                if len(text) > MAX_BULLET_CHARS:
                    issues.append(f"{location}超过 {MAX_BULLET_CHARS} 字")
                verb = _action_prefix(text)
                if not verb:
                    issues.append(f"{location}未以动作词开头")
                elif verb in verbs:
                    issues.append(f"第 {section_index + 1} 节动作词“{verb}”重复")
                else:
                    verbs.add(verb)
                source_fact_ids = bullet.get("source_fact_ids") or []
                source_target_ids = bullet.get("source_target_ids") or []
                referenced_target_ids.update(str(value) for value in source_target_ids)
                if not source_fact_ids and not source_target_ids:
                    issues.append(f"{location}缺少来源")
                if source_target_ids and bullet.get("achieved") is not False:
                    issues.append(f"{location}的学习目标缺少未达成标记")
                if source_fact_ids and not source_target_ids and bullet.get("achieved") is not True:
                    issues.append(f"{location}的事实条目 achieved 状态错误")
                if source_target_ids and not any(
                    str(value) in targets_by_id for value in source_target_ids
                ):
                    issues.append(f"{location}引用的学习目标不存在")
    if kind == "target" and targets_by_id and not referenced_target_ids.intersection(targets_by_id):
        issues.append("蓝图简历未包含任何未达成学习目标")
    return list(dict.fromkeys(issues))


def enforce_page_budget(
    content: dict,
    fact_relevance: dict[str, int] | None = None,
    target_severity: dict[str, str] | None = None,
) -> dict:
    result = deepcopy(content)
    fact_relevance = fact_relevance or {}
    target_severity = target_severity or {}
    while estimate_resume_lines(result) > MAX_RESUME_LINES:
        candidates = []
        target_bullet_count = sum(
            bool(bullet.get("source_target_ids"))
            for section in result.get("sections") or []
            for item in section.get("items") or []
            for bullet in item.get("bullets") or []
        )
        for section_index, section in enumerate(result.get("sections") or []):
            for item_index, item in enumerate(section.get("items") or []):
                for bullet_index, bullet in enumerate(item.get("bullets") or []):
                    if bullet.get("source_target_ids") and target_bullet_count <= 1:
                        continue
                    candidates.append(
                        (
                            _removal_priority(bullet, fact_relevance, target_severity),
                            section_index,
                            item_index,
                            bullet_index,
                        )
                    )
        if not candidates:
            break
        _priority, section_index, item_index, bullet_index = min(candidates)
        del result["sections"][section_index]["items"][item_index]["bullets"][bullet_index]
        result["sections"][section_index]["items"] = [
            item for item in result["sections"][section_index]["items"] if item.get("bullets")
        ]
        result["sections"] = [section for section in result["sections"] if section.get("items")]
    return result


def estimate_resume_lines(content: dict) -> int:
    lines = 3
    if any((content.get("contact") or {}).values()):
        lines += 1
    for section in content.get("sections") or []:
        lines += 1
        for item in section.get("items") or []:
            if any(
                item.get(field)
                for field in ("organization", "role_title", "start_date", "end_date")
            ):
                lines += 1
            for bullet in item.get("bullets") or []:
                lines += max(1, math.ceil(len(str(bullet.get("text") or "")) / 36))
    return lines


def relevance(fact, requirements: list[str]) -> int:
    text = _fact_text(fact).casefold()
    return sum(1 for requirement in requirements if requirement.casefold() in text)


def _fact_item(fact) -> dict:
    text = _bullet_text(_fact_text(fact), DEFAULT_PREFIX.get(fact.category, "积累"))
    return {
        "organization": str(getattr(fact, "organization", "") or ""),
        "role_title": str(getattr(fact, "role_title", "") or ""),
        "location": str(getattr(fact, "location", "") or ""),
        "start_date": str(getattr(fact, "start_date", "") or ""),
        "end_date": str(getattr(fact, "end_date", "") or ""),
        "bullets": [
            {
                "text": text,
                "source_fact_ids": [str(fact.id)],
                "source_target_ids": [],
                "achieved": True,
                "new_claims": [],
            }
        ],
    }


def _target_item(target) -> dict:
    return {
        "organization": "",
        "role_title": "",
        "location": "",
        "start_date": "",
        "end_date": "",
        "bullets": [
            {
                "text": _bullet_text(str(target.deliverable), "完成"),
                "source_fact_ids": [],
                "source_target_ids": [str(target.id)],
                "achieved": False,
                "new_claims": [],
            }
        ],
    }


def _bullet_text(value: str, prefix: str) -> str:
    lines = [
        re.sub(r"\s+", " ", line).strip(" ·|｜") for line in value.splitlines() if line.strip()
    ]
    first_is_metadata = bool(
        lines
        and ("|" in lines[0] or "｜" in lines[0] or re.search(r"(?:19|20)\d{2}[-年./]", lines[0]))
    )
    text = "；".join(lines[1:] if len(lines) > 1 and first_is_metadata else lines)
    if not _action_prefix(text):
        text = f"{prefix}{text}"
    if len(text) > MAX_BULLET_CHARS:
        text = text[: MAX_BULLET_CHARS - 1].rstrip("，,；;。 ") + "…"
    return text


def _fact_text(fact) -> str:
    value_json = getattr(fact, "value_json", {}) or {}
    return str(value_json.get("text", getattr(fact, "label", "")))


def _action_prefix(text: str) -> str:
    return next((prefix for prefix in ACTION_PREFIXES if text.startswith(prefix)), "")


def _dedupe_section_verbs(content: dict) -> dict:
    result = deepcopy(content)
    for section in result.get("sections") or []:
        seen = set()
        for item in section.get("items") or []:
            kept = []
            for bullet in item.get("bullets") or []:
                verb = _action_prefix(str(bullet.get("text") or ""))
                if verb and verb in seen:
                    continue
                if verb:
                    seen.add(verb)
                kept.append(bullet)
            item["bullets"] = kept
        section["items"] = [item for item in section.get("items") or [] if item.get("bullets")]
    result["sections"] = [
        section for section in result.get("sections") or [] if section.get("items")
    ]
    return result


def _removal_priority(
    bullet: dict,
    fact_relevance: dict[str, int],
    target_severity: dict[str, str],
) -> tuple[int, int]:
    target_ids = [str(value) for value in bullet.get("source_target_ids") or []]
    if target_ids:
        severity = min(
            (
                {"low": 0, "medium": 2, "high": 4}.get(target_severity.get(value, "medium"), 2)
                for value in target_ids
            ),
            default=2,
        )
        return severity, 0
    fact_ids = [str(value) for value in bullet.get("source_fact_ids") or []]
    score = min((fact_relevance.get(value, 0) for value in fact_ids), default=0)
    return min(score * 2 + 1, 5), 1
