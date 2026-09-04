import math
import re
from copy import deepcopy

from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import ResumeStructuredV2Output

from .fact_guard import guard_content
from .resume_style import SKILL_SECTION_NAME, is_skill_tag_section

MAX_BULLET_CHARS = 120
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
    "根据",
    "将",
)
CATEGORY_ORDER = {
    "projects": 0,
    "employment": 1,
    "education": 2,
    "skills": 3,
    "certificates": 4,
    "other": 5,
}
SECTION_NAMES = {
    "projects": "项目经历",
    "employment": "实习经历",
    "education": "教育背景",
    "skills": SKILL_SECTION_NAME,
    "certificates": "奖项/校园",
    "other": "其他经历",
}
JD_GAP_SECTION = "对照 JD 尚未具备"
DEFAULT_PREFIX = {
    "employment": "积累",
    "projects": "完成",
    "skills": "掌握",
    "education": "具备",
    "certificates": "具备",
    "other": "积累",
}
RESUME_SYSTEM_PROMPT = (
    "你是中文校招/实习简历编辑，按一页单栏模板改写已确认事实。"
    "章节顺序必须是：项目经历、实习经历、教育背景、技能证书、奖项/校园。"
    "headline 只写求职意向（岗位名），不要写资深、年限或职级。"
    "经历条目写成完整段落：先写任务，再写自己做的动作，最后只写原文已有的产物。"
    "能放进一条里就不要拆开。技能章节 presentation 必须为 tags，每条 bullet 只写工具或技能名，"
    "不要写成「掌握了…」。每个 bullet 必须引用 source_fact_ids 或 source_target_ids；"
    "不得引入来源中不存在的数字、工具、公司、证书，不得把团队成果写成个人成果。"
    "日期未知必须留空。"
    f"经历条目不超过 {MAX_BULLET_CHARS} 字，以动作词开头；不要为了动词不重复而改掉原意，"
    "不要用省略号截断。kind=target 且输入含 capability_targets 时，必须至少选择一条目标，"
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
    match=None,
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
    grouped: dict[str, dict[tuple, dict]] = {}
    for fact in sorted(
        confirmed,
        key=lambda item: (-fact_relevance[str(item.id)], CATEGORY_ORDER.get(item.category, 9)),
    ):
        item = _fact_item(fact)
        if fact.category == "skills":
            key = ("", "", "", "", "")
        else:
            key = (
                str(getattr(fact, "organization", "") or ""),
                str(getattr(fact, "role_title", "") or ""),
                str(getattr(fact, "start_date", "") or ""),
                str(getattr(fact, "end_date", "") or ""),
                fact.label if not getattr(fact, "organization", "") else "",
            )
        bucket = grouped.setdefault(fact.category, {})
        if key in bucket:
            bucket[key]["bullets"].extend(item["bullets"])
        else:
            bucket[key] = item
    content = {
        "content_version": 2,
        "kind": kind,
        "headline": job.title,
        "contact": dict(contact or {}),
        "sections": [
            {"name": SECTION_NAMES.get(category, "其他经历"), "items": list(items.values())}
            for category, items in sorted(
                grouped.items(), key=lambda entry: CATEGORY_ORDER.get(entry[0], 9)
            )
        ],
        "excluded_gaps": [
            requirement
            for requirement in requirements
            if not any(requirement.casefold() in _fact_text(fact).casefold() for fact in confirmed)
        ],
        "gap_summary": _gap_summary(job, match, active_targets, confirmed) if kind == "target" else {},
    }
    if kind == "target" and active_targets:
        content["sections"] = [
            {
                "name": JD_GAP_SECTION,
                "items": [
                    _target_item(target)
                    for target in sorted(
                        active_targets,
                        key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(item.severity, 1),
                    )
                ],
            },
            *content["sections"],
        ]
    content = _normalize_skill_sections(content)
    content = _dedupe_section_verbs(content)
    return enforce_page_budget(content, fact_relevance, target_severity)


def evaluate_resume_content(
    content: dict,
    facts: list,
    targets: list | None,
    *,
    kind: str,
    expected_headline: str | None = None,
    expected_contact: dict | None = None,
) -> dict:
    guard = guard_content(content, facts, targets, mode=kind)
    quality_issues = content_quality_issues(
        content,
        facts,
        targets,
        kind=kind,
        expected_headline=expected_headline,
        expected_contact=expected_contact,
    )
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
    match=None,
) -> dict:
    """Generate once, retry one semantic failure, then use the safe local result."""
    confirmed = [fact for fact in facts if fact.verification_status == "user_confirmed"]
    active_targets = list(targets or []) if kind == "target" else []
    fallback = generate_resume(
        confirmed, job, active_targets, kind=kind, contact=contact, match=match
    )
    payload = _resume_llm_payload(confirmed, job, active_targets, kind, contact, fallback)
    structured, provider_name = await generate_structured(
        task="resume_rewrite",
        system_prompt=RESUME_SYSTEM_PROMPT,
        user_payload=payload,
        response_model=ResumeStructuredV2Output,
    )
    content, evaluation = _prepare_and_evaluate_resume(
        structured.model_dump(), confirmed, job, active_targets, kind, contact, match
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
            structured.model_dump(), confirmed, job, active_targets, kind, contact, match
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
        evaluation = evaluate_resume_content(
            content,
            confirmed,
            active_targets,
            kind=kind,
            expected_headline=job.title,
            expected_contact=contact,
        )
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
                "目标条目优先以“完成”或“学习”开头，放在最前面的对照 JD 章节。"
                "章节顺序：项目、实习、教育、技能证书。技能必须是词条，不要写掌握/熟悉。"
                "所有 new_claims 必须是空数组。要点按动作-任务-结果改写，产物必须来自原文。"
                if targets
                else (
                    "不得引用学习目标；所有 new_claims 必须是空数组。"
                    "章节顺序：项目、实习、教育、技能证书。技能必须是词条，不要写掌握/熟悉。"
                    "要点按动作-任务-结果改写，只保留原文已有的动作、任务和产物。"
                )
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
    contact: dict | None,
    match=None,
) -> tuple[dict, dict]:
    requirements = list(dict.fromkeys([*(job.must_have_json or []), *(job.keywords_json or [])]))
    fact_relevance = {str(fact.id): relevance(fact, requirements) for fact in facts}
    target_severity = {str(target.id): target.severity for target in targets}
    if kind == "target" and not content.get("gap_summary"):
        content = {**content, "gap_summary": _gap_summary(job, match, targets, facts)}
    prepared = _normalize_skill_sections(content)
    prepared = _dedupe_section_verbs(prepared)
    prepared = enforce_page_budget(prepared, fact_relevance, target_severity)
    evaluation = evaluate_resume_content(
        prepared,
        facts,
        targets,
        kind=kind,
        expected_headline=job.title,
        expected_contact=contact,
    )
    return prepared, evaluation


def content_quality_issues(
    content: dict,
    facts: list,
    targets: list | None,
    *,
    kind: str,
    expected_headline: str | None = None,
    expected_contact: dict | None = None,
) -> list[str]:
    issues = []
    if expected_headline is not None and not _safe_headline(
        str(content.get("headline") or ""), expected_headline
    ):
        issues.append("简历标题包含未经来源支持的职业主张")
    if content.get("content_version", 1) == 1:
        return issues
    if content.get("kind") != kind:
        issues.append("简历 kind 与请求模式不一致")
    if expected_contact is not None and _normalized_contact(
        content.get("contact")
    ) != _normalized_contact(expected_contact):
        issues.append("简历联系方式与已确认的原始简历信息不一致")
    facts_by_id = {str(fact.id): fact for fact in facts}
    targets_by_id = {str(target.id): target for target in targets or []}
    referenced_target_ids: set[str] = set()
    for section_index, section in enumerate(content.get("sections") or []):
        skill_tags = is_skill_tag_section(section)
        for item_index, item in enumerate(section.get("items") or []):
            fact_ids = {
                str(value)
                for bullet in item.get("bullets") or []
                for value in bullet.get("source_fact_ids") or []
            }
            referenced_facts = [facts_by_id[value] for value in fact_ids if value in facts_by_id]
            target_only = not fact_ids and any(
                bullet.get("source_target_ids") for bullet in item.get("bullets") or []
            )
            if not target_only:
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
                if not skill_tags and not _action_prefix(text):
                    issues.append(f"{location}未以动作词开头")
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


def _safe_headline(value: str, job_title: str) -> bool:
    """Allow presentation-only wrappers around the selected job title.

    Seniority, years of experience and credentials are not presentation text;
    they must never enter a headline merely because an LLM produced them.
    """

    def normalize(text: str) -> str:
        return re.sub(r"[\s·|｜—–_-]+", "", str(text or "")).strip("，,。；;：:")

    title = normalize(job_title)
    headline = normalize(value)
    return bool(title) and headline in {
        title,
        f"{title}简历",
        f"{title}求职简历",
        f"{title}岗位定制简历",
        f"应聘{title}",
        f"应聘{title}简历",
    }


def _normalized_contact(value: dict | None) -> dict[str, str]:
    contact = value if isinstance(value, dict) else {}
    return {
        field: re.sub(r"\s+", "", str(contact.get(field) or ""))
        for field in ("name", "phone", "email", "city")
    }


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
        if is_skill_tag_section(section):
            tag_text = " / ".join(
                str(bullet.get("text") or "")
                for item in section.get("items") or []
                for bullet in item.get("bullets") or []
                if bullet.get("text")
            )
            lines += max(1, math.ceil(len(tag_text) / 40)) if tag_text else 0
            continue
        for item in section.get("items") or []:
            if any(
                item.get(field)
                for field in ("organization", "role_title", "start_date", "end_date")
            ):
                lines += 1
            for bullet in item.get("bullets") or []:
                lines += max(1, math.ceil(len(str(bullet.get("text") or "")) / 40))
    return lines


def relevance(fact, requirements: list[str]) -> int:
    text = _fact_text(fact).casefold()
    return sum(1 for requirement in requirements if requirement.casefold() in text)


def _fact_item(fact) -> dict:
    if fact.category == "skills":
        tokens = _skill_tokens(_fact_text(fact)) or [_fact_text(fact).strip()]
        return {
            "organization": "",
            "role_title": "",
            "location": "",
            "start_date": "",
            "end_date": "",
            "bullets": [
                {
                    "text": token,
                    "source_fact_ids": [str(fact.id)],
                    "source_target_ids": [],
                    "achieved": True,
                    "new_claims": [],
                }
                for token in tokens
                if token
            ],
        }
    prefix = DEFAULT_PREFIX.get(fact.category, "完成")
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
            for text in _star_texts(_fact_text(fact), prefix)
        ],
    }


def _target_item(target) -> dict:
    requirement = str(getattr(target, "requirement", "") or "")
    deliverable = str(getattr(target, "deliverable", "") or requirement)
    return {
        "organization": "对照 JD",
        "role_title": requirement,
        "location": "",
        "start_date": "",
        "end_date": "",
        "jd_requirement": requirement,
        "jd_evidence": str(getattr(target, "jd_evidence", "") or ""),
        "bullets": [
            {
                "text": _bullet_text(deliverable, "学习"),
                "source_fact_ids": [],
                "source_target_ids": [str(target.id)],
                "achieved": False,
                "new_claims": [],
            }
        ],
    }


def _gap_summary(job, match, targets: list, confirmed: list) -> dict:
    reasons = []
    if match is not None:
        recommendation = str(getattr(match, "recommendation", "") or "")
        scores = getattr(match, "dimension_scores_json", None) or {}
        hard_block = scores.get("hard_requirements", 30) < 15 or recommendation in {"低优先", "不建议"}
        if hard_block:
            reasons.append("硬性要求覆盖不足，所以匹配被压低。")
        for gap in getattr(match, "gaps_json", None) or []:
            requirement = str(gap.get("requirement") or "").strip()
            if requirement:
                reasons.append(f"JD 要求「{requirement}」，已确认事实里没有对应证据。")
        explanation = getattr(match, "ai_explanation_json", None) or {}
        summary = str(explanation.get("summary") or "").strip()
        if summary and summary not in reasons:
            reasons.append(summary)
    for target in targets:
        requirement = str(getattr(target, "requirement", "") or "").strip()
        line = f"JD 要求「{requirement}」，当前尚未达成。"
        if requirement and line not in reasons:
            reasons.append(line)
    return {
        "title": f"对照「{getattr(job, 'title', '该岗位')}」还缺什么",
        "reasons": reasons[:12],
        "unachieved_count": len(targets),
        "confirmed_count": len(confirmed),
    }


def _bullet_text(value: str, prefix: str) -> str:
    texts = _star_texts(value, prefix)
    return texts[0] if texts else prefix


def _star_texts(value: str, prefix: str) -> list[str]:
    """Keep a fact as complete action-task-result bullets; split only when over budget."""
    lines = [
        re.sub(r"\s+", " ", line).strip(" ·|｜") for line in str(value or "").splitlines() if line.strip()
    ]
    first_is_metadata = bool(
        lines
        and ("|" in lines[0] or "｜" in lines[0] or re.search(r"(?:19|20)\d{2}[-年./]", lines[0]))
    )
    body = "，".join(lines[1:] if len(lines) > 1 and first_is_metadata else lines)
    body = re.sub(r"[。；;]+", "，", body)
    body = re.sub(r"[，,]{2,}", "，", body).strip(" ，,")
    if not body:
        return [prefix]
    merged = _ensure_action_prefix(body, prefix)
    if len(merged) <= MAX_BULLET_CHARS:
        return [merged]
    clauses = [part.strip(" ，,") for part in re.split(r"[，,]", body) if part.strip()]
    bullets: list[str] = []
    current = ""
    for clause in clauses:
        joined = clause if not current else f"{current}，{clause}"
        joined = _ensure_action_prefix(joined, prefix)
        if len(joined) <= MAX_BULLET_CHARS:
            current = joined
            continue
        if current:
            bullets.append(current)
        current = _ensure_action_prefix(clause, prefix)
        if len(current) > MAX_BULLET_CHARS:
            bullets.append(_clip_to_budget(current))
            current = ""
    if current:
        bullets.append(current)
    unique = list(dict.fromkeys(text for text in bullets if text))
    return unique[:3] or [_clip_to_budget(merged)]


def _ensure_action_prefix(text: str, prefix: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" ，,；;。")
    if not cleaned:
        return prefix
    if _action_prefix(cleaned):
        return cleaned
    return f"{prefix}{cleaned}"


def _clip_to_budget(text: str) -> str:
    if len(text) <= MAX_BULLET_CHARS:
        return text
    window = text[:MAX_BULLET_CHARS]
    cut = max(window.rfind("，"), window.rfind("、"), window.rfind(" "), window.rfind("；"))
    clipped = window[:cut].rstrip("，,；;。 ") if cut >= 8 else window.rstrip("，,；;。 ")
    return clipped or window[:MAX_BULLET_CHARS]


def _fact_text(fact) -> str:
    value_json = getattr(fact, "value_json", {}) or {}
    return str(value_json.get("text", getattr(fact, "label", "")))


def _action_prefix(text: str) -> str:
    return next((prefix for prefix in ACTION_PREFIXES if text.startswith(prefix)), "")


def _normalize_skill_sections(content: dict) -> dict:
    result = deepcopy(content)
    sections = []
    for section in result.get("sections") or []:
        if not is_skill_tag_section(section):
            sections.append(section)
            continue
        tags = []
        seen: set[str] = set()
        for item in section.get("items") or []:
            for bullet in item.get("bullets") or []:
                source_text = str(bullet.get("text") or "")
                tokens = _skill_tokens(source_text) or ([source_text.strip()] if source_text.strip() else [])
                for token in tokens:
                    key = token.casefold()
                    if not token or key in seen:
                        continue
                    seen.add(key)
                    tags.append({**bullet, "text": token})
        if not tags:
            continue
        sections.append(
            {
                "name": SKILL_SECTION_NAME,
                "presentation": "tags",
                "items": [
                    {
                        "organization": "",
                        "role_title": "",
                        "location": "",
                        "start_date": "",
                        "end_date": "",
                        "bullets": tags,
                    }
                ],
            }
        )
    result["sections"] = sections
    return result


def _skill_tokens(value: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" 。；;，,")
    text = re.sub(
        r"^(?:熟练掌握|熟练使用|熟练|掌握了|掌握|熟悉|了解|精通|具备|使用)+",
        "",
        text,
    ).strip(" ：:，,")
    parts = [part.strip(" ·-") for part in re.split(r"[、，,/／|｜;；]+", text) if part.strip()]
    noise = {"技能", "专业技能", "相关技能", "能力", "软件", "工具"}
    tokens: list[str] = []
    for part in parts:
        part = re.sub(
            r"^(?:熟练掌握|熟练使用|熟练|掌握了|掌握|熟悉|了解|精通|具备|使用)+",
            "",
            part,
        ).strip(" ·-")
        if not part or part in noise:
            continue
        if " " in part and re.fullmatch(r"[A-Za-z0-9+#.\- ]+", part):
            tokens.extend(token for token in part.split() if len(token) >= 2 and token not in noise)
        elif 1 < len(part) <= 32:
            tokens.append(part)
    return list(dict.fromkeys(tokens))


def _dedupe_section_verbs(content: dict) -> dict:
    """Keep original verbs; only add a prefix when a bullet has none."""
    result = deepcopy(content)
    for section in result.get("sections") or []:
        if is_skill_tag_section(section):
            continue
        for item in section.get("items") or []:
            kept = []
            for bullet in item.get("bullets") or []:
                text = _ensure_action_prefix(str(bullet.get("text") or ""), "完成")
                if len(text) > MAX_BULLET_CHARS:
                    text = _clip_to_budget(text)
                kept.append({**bullet, "text": text})
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
