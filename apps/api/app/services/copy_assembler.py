"""Assemble model resume copy into locally owned content_version=3 JSON."""

from __future__ import annotations

import re
from copy import deepcopy

from app.errors import AppError
from app.services.content_contract import (
    iter_bullets,
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
    return validate_content(
        {
            "content_version": 3,
            "factuality_policy": "ai_expansion",
            "kind": kind,
            "headline": str(payload.get("headline") or headline or "").strip() or headline,
            "contact": contact or payload.get("contact") or {},
            "sections": sections,
            "excluded_gaps": list(payload.get("excluded_gaps") or []),
        }
    )


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
    if kept:
        rows.append({**header, "bullets": kept})
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
