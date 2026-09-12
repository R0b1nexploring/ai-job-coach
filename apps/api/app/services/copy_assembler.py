"""Assemble model resume copy into locally owned content_version=3 JSON."""

from __future__ import annotations

import re
from copy import deepcopy

from app.errors import AppError
from app.services.content_contract import (
    STAR_CONTRACT_VERSION,
    iter_bullets,
    is_project_item,
    new_bullet_id,
    normalize_bullet,
    validate_content,
)
from app.services.resume_template import CATEGORY_SECTIONS, SECTION_ORDER

LAYOUT_FIELDS = {
    "html",
    "css",
    "font",
    "font_size",
    "fonts",
    "page",
    "page_size",
    "line_height",
    "margin",
    "pagination",
    "docx",
    "pdf",
    "locked",
}


def assemble_model_copy(
    raw: dict,
    *,
    facts,
    requirements,
    kind: str,
    headline: str,
    contact: dict,
    current_content: dict | None = None,
) -> dict:
    """Keep model text and citations; assign IDs, status, order and experience locally."""
    payload = _without_layout(raw if isinstance(raw, dict) else {})
    fact_index = {_fact_id(fact): fact for fact in facts if _fact_id(fact)}
    req_ids = {str(item.get("id") or "") for item in requirements if item.get("id")}
    current_by_id = {
        str(bullet.get("id") or ""): (section, item, bullet)
        for section, item, bullet in iter_bullets(current_content or {})
        if bullet.get("id")
    }
    grouped: dict[str, list[dict]] = {name: [] for name in SECTION_ORDER}
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        name = _canonical_section(section.get("name") or "")
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            assembled_items = _assemble_item(
                item,
                facts_by_id=fact_index,
                req_ids=req_ids,
                kind=kind,
                current_by_id=current_by_id,
            )
            grouped.setdefault(name, []).extend(assembled_items)
    for name, items in list(grouped.items()):
        grouped[name] = _merge_same_organization_items(items)
    if current_content:
        _restore_locked(grouped, current_content)
    sections = [
        {
            "name": name,
            "presentation": "tags" if name == "技能" else "items",
            "items": grouped[name],
        }
        for name in SECTION_ORDER
        if grouped.get(name)
    ]
    assembled = {
        "content_version": 3,
        "factuality_policy": "ai_expansion",
        "kind": kind,
        "headline": str(payload.get("headline") or headline or "").strip() or headline,
        "contact": contact or payload.get("contact") or {},
        "sections": sections,
        "excluded_gaps": list(payload.get("excluded_gaps") or []),
    }
    if kind == "target":
        assembled["project_story_contract_version"] = STAR_CONTRACT_VERSION
        ensure_target_project_stories(assembled, requirements)
    return validate_content(assembled)


def _assemble_item(
    item: dict,
    *,
    facts_by_id: dict,
    req_ids: set[str],
    kind: str,
    current_by_id: dict,
) -> list[dict]:
    kept: list[dict] = []
    independent: list[dict] = []
    header = {
        "organization": str(item.get("organization") or ""),
        "role_title": str(item.get("role_title") or ""),
        "location": str(item.get("location") or ""),
        "start_date": str(item.get("start_date") or ""),
        "end_date": str(item.get("end_date") or ""),
    }
    for bullet in item.get("bullets") or []:
        if not isinstance(bullet, dict):
            continue
        try:
            assembled, attach = _assemble_bullet(
                bullet,
                header=header,
                facts_by_id=facts_by_id,
                req_ids=req_ids,
                kind=kind,
                current_by_id=current_by_id,
            )
        except AppError:
            continue
        if attach:
            kept.append(assembled)
        else:
            independent.append(
                {
                    **_header_from_bullet(assembled, header),
                    "bullets": [assembled],
                    "entry_kind": "ai_suggestion",
                }
            )
    rows = []
    raw_story = item.get("project_story") if isinstance(item.get("project_story"), dict) else None
    if kept:
        row = {**header, "bullets": kept}
        if raw_story:
            row["project_story"] = deepcopy(raw_story)
        rows.append(row)
    for extra in independent:
        host = next(
            (
                row
                for row in rows
                if extra.get("organization")
                and _organization_matches(row.get("organization"), extra.get("organization"))
            ),
            None,
        )
        if host is not None:
            host.setdefault("bullets", []).extend(extra.get("bullets") or [])
        else:
            rows.append(extra)
    return rows


def ensure_target_project_stories(content: dict, requirements: list[dict]) -> None:
    """Own STAR mappings locally instead of trusting model-supplied IDs.

    The writer may draft the narrative, but every saved linkage is rebuilt
    from the assembled bullets.  That keeps a project story tied to its own
    experience after a model retry or a partial regeneration.
    """
    requirement_text = {
        str(item.get("id") or ""): str(item.get("text") or "")
        for item in requirements
        if isinstance(item, dict) and item.get("id")
    }
    for section in content.get("sections") or []:
        for item in section.get("items") or []:
            if not is_project_item(section, item):
                continue
            bullets = [bullet for bullet in item.get("bullets") or [] if isinstance(bullet, dict)]
            if not bullets:
                continue
            item["project_story"] = _assemble_project_story(
                item.get("project_story"),
                item=item,
                bullets=bullets,
                requirement_text=requirement_text,
            )


def _assemble_project_story(raw: object, *, item: dict, bullets: list[dict], requirement_text: dict[str, str]) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    bullet_ids = _ordered_values(bullet.get("id") for bullet in bullets)
    source_fact_ids = _ordered_values(
        fact_id for bullet in bullets for fact_id in (bullet.get("source_fact_ids") or [])
    )
    requirement_ids = _ordered_values(
        requirement_id
        for bullet in bullets
        for requirement_id in (bullet.get("requirement_ids") or bullet.get("source_target_ids") or [])
    )
    source_target_ids = _ordered_values(
        requirement_id for bullet in bullets for requirement_id in (bullet.get("source_target_ids") or [])
    )
    target_requirement = "、".join(
        requirement_text.get(requirement_id, "") for requirement_id in requirement_ids if requirement_text.get(requirement_id)
    )
    title = _story_text(raw.get("title")) or _story_title(item) or "目标项目"
    has_unverified_content = bool(requirement_ids) or any(
        bullet.get("achieved") is False or bullet.get("verification_status") == "ai_generated"
        for bullet in bullets
    )
    achieved = bool(source_fact_ids) and not has_unverified_content
    verification_status = "source_based" if achieved else "ai_generated"
    situation = raw.get("situation") if isinstance(raw.get("situation"), dict) else {}
    task = raw.get("task") if isinstance(raw.get("task"), dict) else {}
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    first_bullet = _story_text(bullets[0].get("text"))
    context = _story_text(situation.get("context")) or (
        f"围绕「{target_requirement}」补齐可展示的项目能力" if target_requirement else "围绕目标岗位设计一段可验证的项目实践"
    )
    problem = _story_text(situation.get("problem")) or (
        "需要把岗位要求转为可拆分、可验证的项目产出" if not achieved else "需要在既有项目约束下完成可复盘的交付"
    )
    role = _story_text(task.get("role")) or ("计划负责人" if not achieved else (_story_text(item.get("role_title")) or "项目参与者"))
    goal = _story_text(task.get("goal")) or (
        f"形成能对应{target_requirement}的完整交付与验证记录" if target_requirement else "形成可演示、可复盘的项目交付"
    )
    constraints = _text_list(task.get("constraints")) or ["以已保存的素材和岗位要求为边界，不把计划写成已完成经历"]
    actions = _story_actions(raw.get("actions"), achieved=achieved, first_bullet=first_bullet, target_requirement=target_requirement)
    deliverables = _text_list(result.get("deliverables")) or [
        "可演示的项目产出", "过程记录与版本说明"
    ]
    verification_method = _story_text(result.get("verification_method")) or "用交付物、过程记录和验收条件逐项核验"
    metrics = _story_metrics(result.get("metrics"), achieved=achieved)
    return {
        "schema_version": STAR_CONTRACT_VERSION,
        "project_id": _story_text(raw.get("project_id")) or f"project:{bullet_ids[0]}",
        "title": title,
        "situation": {"context": context, "problem": problem},
        "task": {"role": role, "goal": goal, "constraints": constraints},
        "actions": actions,
        "result": {
            "deliverables": deliverables,
            "verification_method": verification_method,
            "metrics": metrics,
        },
        "bullet_ids": bullet_ids,
        "source_fact_ids": source_fact_ids,
        "source_target_ids": source_target_ids,
        "requirement_ids": requirement_ids,
        "verification_status": verification_status,
        "achieved": achieved,
    }


def _story_actions(raw: object, *, achieved: bool, first_bullet: str, target_requirement: str) -> list[dict]:
    values = raw if isinstance(raw, list) else []
    actions = []
    for value in values:
        if not isinstance(value, dict):
            continue
        step = _story_text(value.get("step"))
        method = _story_text(value.get("method"))
        if not step or not method:
            continue
        actions.append(
            {
                "step": step,
                "method": method,
                "rationale": _story_text(value.get("rationale")) or "说明该方法如何服务项目目标",
                "difficulty": _story_text(value.get("difficulty")) or "明确约束、风险与取舍",
                "contribution": _story_text(value.get("contribution")) or (
                    "本人负责的已确认部分" if achieved else "计划负责方案拆解、执行记录与验证"
                ),
            }
        )
    if actions:
        return actions
    focus = target_requirement or first_bullet or "目标项目能力"
    return [
        {
            "step": f"将「{focus}」拆成可执行的工作包与验收项",
            "method": "先定义输入、输出和验证方式，再按阶段保留过程记录",
            "rationale": "让每个行动都能追溯到岗位要求和最终交付",
            "difficulty": "在时间、素材与技术边界内做取舍",
            "contribution": "本人负责的已确认部分" if achieved else "计划负责方案拆解、执行记录与验证",
        }
    ]


def _story_metrics(raw: object, *, achieved: bool) -> list[dict]:
    metrics = []
    for value in raw if isinstance(raw, list) else []:
        if not isinstance(value, dict):
            continue
        name, metric_value = _story_text(value.get("name")), _story_text(value.get("value"))
        if not name and not metric_value:
            continue
        requested_kind = _story_text(value.get("kind"))
        kind = "observed" if achieved and requested_kind == "observed" else "target"
        metrics.append(
            {
                "name": name or "验收指标",
                "value": metric_value or "待完成后记录",
                "kind": kind,
                "conditions": _story_text(value.get("conditions")) or "记录测量口径、环境与验收条件",
            }
        )
    if metrics:
        return metrics
    return [
        {
            "name": "验收指标",
            "value": "待完成后记录" if not achieved else "以保存材料中的实际结果为准",
            "kind": "target" if not achieved else "observed",
            "conditions": "记录测量口径、环境与验收条件",
        }
    ]


def _ordered_values(values) -> list[str]:
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _ordered_values(value)


def _story_text(value: object) -> str:
    return str(value or "").strip()


def _story_title(item: dict) -> str:
    return _story_text(item.get("organization")) or _story_text(item.get("role_title"))


def _assemble_bullet(
    bullet: dict,
    *,
    header: dict,
    facts_by_id: dict,
    req_ids: set[str],
    kind: str,
    current_by_id: dict,
) -> tuple[dict, bool]:
    current = current_by_id.get(str(bullet.get("id") or ""))
    current_bullet = current[2] if current else {}
    cited_facts = [str(item) for item in (bullet.get("source_fact_ids") or []) if str(item)]
    valid_facts = [fact_id for fact_id in cited_facts if fact_id in facts_by_id]
    cited_reqs = [
        str(item)
        for item in (bullet.get("requirement_ids") or bullet.get("source_target_ids") or [])
        if str(item)
    ]
    valid_reqs = [req_id for req_id in cited_reqs if req_id in req_ids]
    experience_keys = {_experience_key(facts_by_id[fact_id]) for fact_id in valid_facts}
    cross_experience = len(experience_keys) > 1
    matched_header = True
    if valid_facts and not cross_experience:
        fact = facts_by_id[valid_facts[0]]
        matched_header = _organization_matches(
            header.get("organization"),
            getattr(fact, "organization", ""),
        )
    attach = bool(valid_facts) and not cross_experience and matched_header
    if cross_experience or not matched_header:
        valid_facts = []
        attach = False
    new_claims = [str(item) for item in (bullet.get("new_claims") or []) if str(item)]
    supported = bool(valid_facts) and not new_claims
    verification = "source_based" if supported else "ai_generated"
    achieved = bool(current_bullet.get("achieved")) if current_bullet else (kind == "submittable" and supported)
    if verification == "ai_generated" or valid_reqs:
        achieved = False
    incoming_id = str(bullet.get("id") or "")
    bullet_id = incoming_id if incoming_id in current_by_id else new_bullet_id()
    normalized = normalize_bullet(
        {
            "id": bullet_id,
            "text": bullet.get("text"),
            "source_fact_ids": valid_facts,
            "source_target_ids": valid_reqs if kind == "target" else [],
            "requirement_ids": valid_reqs,
            "achieved": achieved,
            "locked": bool(current_bullet.get("locked")),
            "new_claims": new_claims,
            "verification_status": verification,
        },
        default_achieved=kind == "submittable",
    )
    if verification == "ai_generated":
        normalized["verification_status"] = "ai_generated"
        normalized["achieved"] = False
    return normalized, attach or bool(valid_reqs and kind == "target" and matched_header)


def _restore_locked(grouped: dict[str, list[dict]], current_content: dict) -> None:
    locked = [
        (section, item, bullet)
        for section, item, bullet in iter_bullets(current_content)
        if bullet.get("locked")
    ]
    if not locked:
        return
    present = {
        str(bullet.get("id") or "")
        for items in grouped.values()
        for item in items
        for bullet in item.get("bullets") or []
    }
    for section, item, bullet in locked:
        if str(bullet.get("id") or "") in present:
            continue
        name = _canonical_section(section.get("name") or "")
        grouped.setdefault(name, []).append(
            {
                "organization": item.get("organization") or "",
                "role_title": item.get("role_title") or "",
                "location": item.get("location") or "",
                "start_date": item.get("start_date") or "",
                "end_date": item.get("end_date") or "",
                "bullets": [deepcopy(bullet)],
            }
        )


def _canonical_section(name: str) -> str:
    if name in SECTION_ORDER:
        return name
    mapping = {
        "教育": "教育背景",
        "教育经历": "教育背景",
        "实习": "实习/工作",
        "工作经历": "实习/工作",
        "项目经历": "项目/科研/竞赛",
        "项目": "项目/科研/竞赛",
        "证书": "奖项证书",
        "技能证书": "技能",
    }
    if name in mapping:
        return mapping[name]
    return CATEGORY_SECTIONS.get(name, "项目/科研/竞赛")


def _merge_same_organization_items(items: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for item in items:
        host = next(
            (
                row
                for row in merged
                if item.get("organization")
                and _organization_matches(row.get("organization"), item.get("organization"))
            ),
            None,
        )
        if host is not None:
            host.setdefault("bullets", []).extend(item.get("bullets") or [])
            continue
        merged.append(item)
    return merged


def _compact_label(value: str) -> str:
    return re.sub(r"[\s\-–—/.，,。]", "", str(value or "")).lower()


def _organization_matches(header_org, fact_org) -> bool:
    left, right = _compact_label(header_org), _compact_label(fact_org)
    if not left or not right:
        return True
    return left == right or left in right or right in left


def _experience_key(fact) -> tuple[str, str, str, str]:
    return (
        str(getattr(fact, "material_id", "") or ""),
        str(getattr(fact, "organization", "") or ""),
        str(getattr(fact, "role_title", "") or ""),
        str(getattr(fact, "start_date", "") or ""),
    )


def _fact_id(fact) -> str:
    return str(getattr(fact, "id", "") or "")


def _header_from_bullet(bullet: dict, header: dict) -> dict:
    if any(header.values()):
        return dict(header)
    return {
        "organization": "",
        "role_title": "建议经历",
        "location": "",
        "start_date": "",
        "end_date": "",
    }


def _without_layout(payload: dict) -> dict:
    cleaned = {
        key: value for key, value in payload.items() if key not in LAYOUT_FIELDS
    }
    sections = []
    for section in cleaned.get("sections") or []:
        if not isinstance(section, dict):
            continue
        items = []
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            bullets = []
            for bullet in item.get("bullets") or []:
                if isinstance(bullet, dict):
                    bullets.append(
                        {key: value for key, value in bullet.items() if key not in LAYOUT_FIELDS}
                    )
            items.append(
                {
                    key: value
                    for key, value in item.items()
                    if key not in LAYOUT_FIELDS
                }
                | {"bullets": bullets}
            )
        sections.append({**section, "items": items})
    cleaned["sections"] = sections
    return cleaned
