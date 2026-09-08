"""Local bullet lock/reorder. Re-validates saved content without calling the writer."""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.errors import AppError
from app.models.entities import ResumeBundle, ResumeFact, ResumeVersion, User, now
from app.services.content_contract import iter_bullets, validate_content
from app.services.quality_service import evaluate_version, report_guard_passed
from app.services.quota_service import request_fingerprint


def lock_bullet(db: Session, user: User, version_id: str, bullet_id: str, locked: bool) -> ResumeVersion:
    version = _owned_version(db, user, version_id)
    content = deepcopy(version.content_json or {})
    found = False
    for _section, _item, bullet in iter_bullets(content):
        if bullet.get("id") == bullet_id:
            bullet["locked"] = locked
            found = True
    if not found:
        raise AppError("RESUME_BULLET_NOT_FOUND", "要点不存在。", 404)
    return _persist_local_edit(db, user, version, content, source="lock")


def reorder_bullet(
    db: Session,
    user: User,
    version_id: str,
    bullet_id: str,
    direction: str,
) -> ResumeVersion:
    """Move one bullet within its experience while re-running v3 gates."""
    version = _owned_version(db, user, version_id)
    content = deepcopy(version.content_json or {})
    found = False
    for _section, item, _bullet in iter_bullets(content):
        bullets = item.get("bullets") or []
        index = next((i for i, row in enumerate(bullets) if row.get("id") == bullet_id), None)
        if index is None:
            continue
        target = index - 1 if direction == "up" else index + 1
        if direction not in {"up", "down"} or target < 0 or target >= len(bullets):
            raise AppError("RESUME_BULLET_EDGE", "该要点已经在当前位置。", 409)
        bullets[index], bullets[target] = bullets[target], bullets[index]
        found = True
        break
    if not found:
        raise AppError("RESUME_BULLET_NOT_FOUND", "要点不存在。", 404)
    return _persist_local_edit(db, user, version, content, source="reorder")


def _owned_version(db: Session, user: User, version_id: str) -> ResumeVersion:
    version = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id, ResumeVersion.user_id == user.id
        )
    )
    if not version:
        raise AppError("RESUME_VERSION_NOT_FOUND", "简历版本不存在。", 404)
    return version


def _persist_local_edit(
    db: Session,
    user: User,
    version: ResumeVersion,
    content: dict,
    *,
    source: str,
) -> ResumeVersion:
    if int(content.get("content_version") or 0) >= 3:
        content = validate_content(content)
    facts, requirements = _facts_and_requirements(db, user, version)
    evaluation = evaluate_version(
        content=content,
        facts=facts,
        requirements=requirements,
        mode=version.kind,
    )
    from app.services.bundle_service import _public_quality_report, stale_guides_for_version

    old_hash = version.content_hash
    version.content_json = content
    version.traceability_json = {
        **(version.traceability_json or {}),
        "guard_items": (evaluation.get("guard") or {}).get("items") or [],
        "quality_issues": evaluation.get("issues") or [],
        "last_edit_source": source,
    }
    version.quality_report_json = {
        **_public_quality_report(evaluation),
        "content_hash": request_fingerprint(content),
    }
    version.content_hash = request_fingerprint(content)
    version.guard_status = "passed" if report_guard_passed(evaluation) else "blocked"
    version.unachieved_count = int(evaluation.get("unachieved_count") or 0)
    flag_modified(version, "content_json")
    version.updated_at = now()
    db.flush()
    if version.content_hash != old_hash:
        stale_guides_for_version(db, version)
    return version


def _facts_and_requirements(db: Session, user: User, version: ResumeVersion) -> tuple[list, list]:
    if version.bundle_id:
        from app.services.bundle_service import _generation_inputs

        bundle = db.get(ResumeBundle, version.bundle_id)
        if bundle is not None:
            inputs = _generation_inputs(db, bundle)
            return inputs["facts"], inputs["requirements"]
    facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == version.base_resume_id,
                ResumeFact.user_id == user.id,
                ResumeFact.verification_status == "user_confirmed",
            )
        )
    )
    return facts, []
