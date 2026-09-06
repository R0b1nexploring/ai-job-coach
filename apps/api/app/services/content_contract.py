"""content_version=3 bullet contract."""

from __future__ import annotations

import uuid

from app.errors import AppError

REQUIRED_BULLET_FIELDS = (
    "id",
    "text",
    "source_fact_ids",
    "source_target_ids",
    "requirement_ids",
    "achieved",
    "locked",
    "new_claims",
)


def new_bullet_id() -> str:
    return str(uuid.uuid4())


def normalize_bullet(raw: dict, *, default_achieved: bool = True) -> dict:
    if not isinstance(raw, dict):
        raise AppError("RESUME_BULLET_INVALID", "简历要点格式无效。", 422)
    bullet = {
        "id": str(raw.get("id") or new_bullet_id()),
        "text": str(raw.get("text") or "").strip(),
        "source_fact_ids": [str(item) for item in (raw.get("source_fact_ids") or []) if str(item)],
        "source_target_ids": [
            str(item) for item in (raw.get("source_target_ids") or []) if str(item)
        ],
        "requirement_ids": [str(item) for item in (raw.get("requirement_ids") or []) if str(item)],
        "achieved": bool(raw["achieved"]) if "achieved" in raw else default_achieved,
        "locked": bool(raw.get("locked")),
        "new_claims": list(raw.get("new_claims") or []),
        "verification_status": (
            "ai_generated" if raw.get("verification_status") == "ai_generated"
            else "source_based"
        ),
    }
    if not bullet["text"]:
        raise AppError("RESUME_BULLET_INVALID", "简历要点不能为空。", 422)
    return bullet


def validate_content(content: dict) -> dict:
    if not isinstance(content, dict):
        raise AppError("RESUME_CONTENT_INVALID", "简历内容格式无效。", 422)
    if int(content.get("content_version") or 0) != 3:
        raise AppError("RESUME_CONTENT_INVALID", "新生成简历必须使用 content_version=3。", 422)
    sections = []
    for section in content.get("sections") or []:
        items = []
        for item in section.get("items") or []:
            bullets = [normalize_bullet(bullet) for bullet in item.get("bullets") or []]
            if not bullets:
                continue
            items.append({**item, "bullets": bullets})
        if items:
            sections.append({**section, "items": items})
    normalized = {**content, "content_version": 3, "sections": sections}
    return normalized


def iter_bullets(content: dict):
    for section in content.get("sections") or []:
        for item in section.get("items") or []:
            for bullet in item.get("bullets") or []:
                if isinstance(bullet, dict):
                    yield section, item, bullet


def visible_bullets(content: dict) -> list[dict]:
    return [bullet for _section, _item, bullet in iter_bullets(content)]
