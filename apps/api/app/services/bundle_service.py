"""Create and generate paired resume bundles through a durable task boundary."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.errors import AppError
from app.models.entities import (
    InterviewGuide,
    QuotaLedger,
    QuotaReservation,
    Resume,
    ResumeBundle,
    ResumeBundleRun,
    ResumeFact,
    ResumeVersion,
    TargetProfile,
    User,
    now,
    uid,
)
from app.providers.llm.base import ProviderError
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import (
    ResumeBulletRewriteOutput,
    ResumePairV3Output,
    ResumeStructuredV3Output,
)
from app.services.content_contract import (
    iter_bullets,
    new_bullet_id,
    normalize_bullet,
    validate_content,
    visible_bullets,
)
from app.services.copy_assembler import assemble_model_copy
from app.services.experience_service import (
    confirmed_facts_for_generation,
    draft_materials_for_generation,
    get_or_create_library_resume,
)
from app.services.quality_service import (
    evaluate_version,
    evaluate_version_with_critic,
    quality_report_status,
    report_guard_passed,
)
from app.services.quota_service import change, request_fingerprint, was_created
from app.services.resume_template import (
    CATEGORY_SECTIONS,
    SECTION_ORDER,
    template_snapshot,
)
from app.services.target_profile_service import (
    list_profile_sources,
    owned_profile,
    refresh_profile_if_sources_changed,
)

RESUME_REWRITE_SYSTEM_PROMPT = (
    "你是中文校招/实习简历编辑。根据素材和目标画像改写简历，优先保留原经历。"
    "必须覆盖输入 facts 中出现过的每一个组织，不得删掉实习或教育，不得编造未出现的公司名。"
    "同一 organization 的要点放在同一个 item 下；教育背景单独成区；技能用 presentation=tags。"
    "公司名只用 facts.organization 里的短名称，不要把职责段落、奖项或课程当成公司名。"
    "改写句子，但保留原组织、起止时间和本人实际做的事。每条 bullet 不超过 60 字。"
    "source_fact_ids / requirement_ids 只能引用输入中的 id，没有就留空，禁止编造。"
    "有事实 id 的条目 verification_status=source_based；仅扩写的条目才是 ai_generated 并记录 new_claims。"
    "蓝图未达成项 achieved=false。输出严格 JSON。"
)
RESUME_REWRITE_EXISTING_PROMPT = (
    "输入含 current_content 时，必须在现有简历上改写，不要退回原始事实清单或基础模板。"
    "scope=bullet 时只改进 focus_bullet_id 对应要点，保留其 id、来源字段和其余要点。"
    "scope=section 时只重写 focus_section_name，其余分区保持原结构。"
    "已有扩写内容和 AI 补充条目可以优化表达，不得整份还原成未改写的事实原文。"
)
RESUME_REWRITE_PAIR_PROMPT = (
    f"{RESUME_REWRITE_SYSTEM_PROMPT} "
    "一次同时输出求职版和蓝图，顶层只能有 submittable 与 target 两个对象，形状相同。"
    "两份同源：同一段经历的组织、时间和本人贡献不得互相矛盾。"
    "求职版只放可投递内容，分区顺序为教育背景、实习/工作、项目/科研/竞赛、奖项证书、技能。"
    "蓝图可含未达成目标，achieved=false。"
    "contact 直接使用输入 contact。不要输出布局、HTML、字体或持久 ID。"
    "技能区必须写入输入里出现过的工具、语言和证书名称。"
    "控制篇幅：每个 item 1 到 3 条要点，整份 JSON 必须一次写完。"
)
_TERMINAL_BUNDLE_STATUSES = frozenset({"ready", "degraded", "failed"})
CLAIM_STALE_AFTER = timedelta(seconds=90)
CLAIM_LEASE = timedelta(seconds=90)
MAX_BUNDLE_ATTEMPTS = 3
logger = logging.getLogger(__name__)


def dump_bundle(db: Session, bundle: ResumeBundle) -> dict:
    versions = list(
        db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == bundle.id))
    )
    guides = list(
        db.scalars(select(InterviewGuide).where(InterviewGuide.bundle_id == bundle.id))
    )
    run = db.get(ResumeBundleRun, bundle.id)
    status = _effective_bundle_status(bundle, run)
    return {
        "id": bundle.id,
        "status": status,
        "base_resume_id": bundle.base_resume_id,
        "target_profile_id": bundle.target_profile_id,
        "request_hash": bundle.request_hash,
        "generation_metadata_json": bundle.generation_metadata_json,
        "template_snapshot_json": {
            key: value
            for key, value in (bundle.template_snapshot_json or {}).items()
            if key != "private"
        },
        "versions": {
            version.kind: {
                "id": version.id,
                "status": version.guard_status,
                "kind": version.kind,
                "content_hash": version.content_hash,
                "unachieved_count": version.unachieved_count,
                "quality_status": (version.quality_report_json or {}).get("status"),
            }
            for version in versions
        },
        "guides": {
            guide.kind: {"id": guide.id, "status": guide.status}
            for guide in guides
        },
        "run": {
            "status": run.status if run else None,
            "phase": run.phase if run else None,
            "attempts": run.attempts if run else 0,
            "max_attempts": run.max_attempts if run else MAX_BUNDLE_ATTEMPTS,
            "last_error": _safe_error(run.last_error if run else ""),
            "public_error_code": run.public_error_code if run else "",
        },
        "error": _safe_error((bundle.generation_metadata_json or {}).get("error_message") or (run.last_error if run else "")),
        "can_retry": status in {"failed", "queued"},
        "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
        "updated_at": bundle.updated_at.isoformat() if bundle.updated_at else None,
    }


def owned_bundle(db: Session, user: User, bundle_id: str) -> ResumeBundle:
    row = db.scalar(
        select(ResumeBundle).where(
            ResumeBundle.id == bundle_id, ResumeBundle.user_id == user.id
        )
    )
    if not row:
        raise AppError("RESUME_BUNDLE_NOT_FOUND", "简历包不存在。", 404)
    return row


def _safe_error(message: str) -> str:
    text = str(message or "")
    for blocked in ("prompt", "raw_jd", "password", "api_key"):
        if blocked in text.lower():
            return "生成失败，请重试。"
    return text[:200]


def _fact_text(fact) -> str:
    return str((fact.value_json or {}).get("text") or fact.source_text or fact.label or "")


def _fact_input(fact) -> dict:
    return {
        "id": fact.id,
        "category": getattr(fact, "category", "") or "",
        "label": getattr(fact, "label", "") or "",
        "organization": getattr(fact, "organization", "") or "",
        "role_title": getattr(fact, "role_title", "") or "",
        "location": getattr(fact, "location", "") or "",
        "start_date": getattr(fact, "start_date", "") or "",
        "end_date": getattr(fact, "end_date", "") or "",
        "text": _fact_text(fact),
        "source_text": getattr(fact, "source_text", "") or "",
        "verification_status": getattr(fact, "verification_status", "") or "",
        "material_id": getattr(fact, "material_id", "") or "",
    }


def _requirement_input(requirement: dict) -> dict:
    return {
        "id": requirement.get("id"),
        "text": requirement.get("text"),
        "category": requirement.get("category"),
        "priority": requirement.get("priority"),
    }


def _generation_request_hash(*, resume_id: str, profile_id: str, profile_version, facts, draft_materials=None) -> str:
    return request_fingerprint(
        {
            "operation": "resume_bundle.create",
            "factuality_policy": "ai_expansion",
            "resume_id": resume_id,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "facts": [
                {
                    "id": fact.id,
                    "text": _fact_text(fact),
                    "updated_at": fact.updated_at.isoformat() if getattr(fact, "updated_at", None) else "",
                }
                for fact in sorted(facts, key=lambda item: item.id)
            ],
            "draft_materials": [
                {"id": item.get("id"), "summary": item.get("summary"), "title": item.get("title")}
                for item in sorted(draft_materials or [], key=lambda row: str(row.get("id") or ""))
            ],
        }
    )


def _default_bundle_idempotency_key(*, user_id: str, resume_id: str, profile_id: str, payload_hash: str) -> str:
    return f"resume-bundle:{user_id}:{resume_id}:{profile_id}:{payload_hash}"


def _writer_source(provider_name: str) -> str:
    return "fallback" if provider_name == "mock_fallback" else "model"


def _usable_fallback_org(value: str) -> str:
    text = str(value or "").strip()
    if len(text) > 40 or text.startswith(("负责", "公司需要", "通过分析")):
        return ""
    return text


def _effective_bundle_status(bundle: ResumeBundle, run: ResumeBundleRun | None) -> str:
    if bundle.status in _TERMINAL_BUNDLE_STATUSES:
        return bundle.status
    if run is not None and run.status in _TERMINAL_BUNDLE_STATUSES:
        return run.status
    return bundle.status


def _reconcile_bundle_run(db: Session, bundle: ResumeBundle) -> ResumeBundle:
    run = db.get(ResumeBundleRun, bundle.id)
    if run is None:
        return bundle
    if bundle.status in _TERMINAL_BUNDLE_STATUSES and run.status != bundle.status:
        run.status = bundle.status
        run.updated_at = now()
    elif run.status in _TERMINAL_BUNDLE_STATUSES and bundle.status != run.status:
        bundle.status = run.status
        bundle.updated_at = now()
    db.flush()
    return bundle


def resolve_generation_resume(db: Session, user: User, base_resume_id: str | None) -> Resume:
    if base_resume_id:
        resume = db.scalar(
            select(Resume).where(
                Resume.id == base_resume_id,
                Resume.user_id == user.id,
                Resume.deleted_at.is_(None),
            )
        )
        if not resume:
            raise AppError("RESUME_NOT_FOUND", "简历不存在。", 404)
        return resume
    return get_or_create_library_resume(db, user)


def create_bundle(
    db: Session,
    user: User,
    *,
    base_resume_id: str | None,
    target_profile_id: str,
    idempotency_key: str | None = None,
) -> ResumeBundle:
    resume = resolve_generation_resume(db, user, base_resume_id)
    profile = owned_profile(db, user, target_profile_id)
    refresh_profile_if_sources_changed(db, profile)
    facts = confirmed_facts_for_generation(db, user, resume)
    draft_materials = draft_materials_for_generation(db, user)
    payload_hash = _generation_request_hash(
        resume_id=resume.id,
        profile_id=profile.id,
        profile_version=profile.version,
        facts=facts,
        draft_materials=draft_materials,
    )
    key = (idempotency_key or "").strip() or _default_bundle_idempotency_key(
        user_id=user.id,
        resume_id=resume.id,
        profile_id=profile.id,
        payload_hash=payload_hash,
    )
    existing = db.scalar(
        select(ResumeBundle).where(
            ResumeBundle.user_id == user.id,
            ResumeBundle.idempotency_key == key,
        )
    )
    if existing:
        if existing.request_hash and existing.request_hash != payload_hash:
            raise AppError("IDEMPOTENCY_KEY_REUSED", "同一幂等键不能用于不同的生成请求。", 409)
        return _reconcile_bundle_run(db, existing)

    active = db.scalar(
        select(ResumeBundle.id)
        .where(
            ResumeBundle.user_id == user.id,
            ResumeBundle.status.in_(["queued", "generating"]),
        )
        .limit(1)
    )
    if active:
        raise AppError(
            "AI_TASK_IN_PROGRESS",
            "已有简历生成任务正在处理中，请等待完成后再提交。",
            409,
        )

    bundle_id = uid()
    sources = list_profile_sources(db, profile.id)
    snapshot = template_snapshot()
    target_snapshot = deepcopy(profile.snapshot_json or {})
    target_snapshot["title"] = profile.title
    input_snapshot = {
        "facts": [_fact_input(fact) for fact in facts],
        "draft_materials": draft_materials,
        "contact": deepcopy(resume.contact_json or {}),
        "headline": profile.title,
        "job_id": sources[0].job_id if len(sources) == 1 else None,
    }
    ledger = change(
        db,
        user_id=user.id,
        quota_type="resume",
        delta=-1,
        reason="生成双轨简历包",
        idempotency_key=key,
        reference_type="resume_bundle",
        reference_id=bundle_id,
        request_hash=payload_hash,
    )
    if not was_created(ledger) and ledger.reference_id:
        reused = db.get(ResumeBundle, ledger.reference_id)
        if reused:
            return _reconcile_bundle_run(db, reused)
    if not was_created(ledger):
        raise AppError(
            "IDEMPOTENCY_RESULT_UNAVAILABLE",
            "相同请求仍在处理中，请稍后使用同一幂等键重试。",
            409,
        )
    bundle = ResumeBundle(
        id=bundle_id,
        user_id=user.id,
        base_resume_id=resume.id,
        target_profile_id=profile.id,
        status="queued",
        facts_snapshot_json={"ids": [fact.id for fact in facts], **input_snapshot},
        target_snapshot_json=target_snapshot,
        template_snapshot_json=snapshot,
        request_hash=payload_hash,
        idempotency_key=key,
        generation_metadata_json={"profile_version": profile.version},
    )
    db.add(bundle)
    db.flush()
    db.add(
        QuotaReservation(
            ledger_id=ledger.id,
            user_id=user.id,
            quota_type=ledger.quota_type,
            amount=-ledger.delta,
            resource_type="resume_bundle",
            resource_id=bundle.id,
        )
    )
    db.add(
        ResumeBundleRun(
            bundle_id=bundle.id,
            user_id=user.id,
            status="queued",
            phase="queued",
            request_hash=payload_hash,
            input_snapshot_json={
                "facts": input_snapshot["facts"],
                "target": target_snapshot,
                "contact": input_snapshot["contact"],
                "headline": input_snapshot["headline"],
                "job_id": input_snapshot["job_id"],
            },
            max_attempts=MAX_BUNDLE_ATTEMPTS,
        )
    )
    db.flush()
    return bundle


def claim_bundle_run(db: Session, bundle_id: str, *, stale_after: timedelta | None = None) -> str | None:
    """Atomically claim a queued or stale generating run. Returns claim token or None."""
    token = uid()
    current = now()
    cutoff = current - (stale_after if stale_after is not None else CLAIM_STALE_AFTER)
    result = db.execute(
        update(ResumeBundleRun)
        .where(
            ResumeBundleRun.bundle_id == bundle_id,
            or_(
                ResumeBundleRun.status == "queued",
                and_(
                    ResumeBundleRun.status == "generating",
                    or_(
                        ResumeBundleRun.lease_expires_at <= current,
                        ResumeBundleRun.updated_at <= cutoff,
                    ),
                ),
            ),
            ResumeBundleRun.attempts < ResumeBundleRun.max_attempts,
        )
        .values(
            status="generating",
            phase="writing",
            claim_token=token,
            last_error="",
            public_error_code="",
            attempts=ResumeBundleRun.attempts + 1,
            lease_expires_at=current + CLAIM_LEASE,
            heartbeat_at=current,
            updated_at=current,
        )
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        return None
    bundle = db.get(ResumeBundle, bundle_id)
    if bundle is not None:
        bundle.status = "generating"
        bundle.updated_at = current
    db.flush()
    return token


def heartbeat_bundle_run(db: Session, bundle_id: str, token: str) -> bool:
    """Extend a worker lease only while the worker still owns the claim."""
    current = now()
    result = db.execute(
        update(ResumeBundleRun)
        .where(
            ResumeBundleRun.bundle_id == bundle_id,
            ResumeBundleRun.claim_token == token,
            ResumeBundleRun.status == "generating",
        )
        .values(
            heartbeat_at=current,
            lease_expires_at=current + CLAIM_LEASE,
            updated_at=current,
        )
    )
    db.flush()
    return result.rowcount == 1


def _claimed_bundle_run(db: Session, bundle_id: str, token: str) -> ResumeBundleRun | None:
    """Read the current claim, bypassing the session identity-map cache.

    A worker can spend several seconds outside the database while the model is
    running.  A stale ORM instance is therefore not sufficient for the final
    claim check: another worker may have taken over the lease in the meantime.
    PostgreSQL also locks the run row while the result is being persisted so a
    takeover cannot interleave with the version writes.
    """
    statement = (
        select(ResumeBundleRun)
        .where(
            ResumeBundleRun.bundle_id == bundle_id,
            ResumeBundleRun.claim_token == token,
            ResumeBundleRun.status == "generating",
        )
        .execution_options(populate_existing=True)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    return db.scalar(statement)


async def process_queued_bundles(db: Session, *, limit: int = 10) -> int:
    statement = (
        select(ResumeBundleRun.bundle_id)
        .where(ResumeBundleRun.status.in_(["queued", "generating"]))
        .order_by(ResumeBundleRun.created_at)
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    bundle_ids = list(db.scalars(statement))
    # SQLite cannot safely upgrade a read transaction to a write transaction.
    # The claim UPDATE below remains the authority on every backend.
    db.rollback()
    processed = 0
    for bundle_id in bundle_ids:
        claimed = await process_bundle(db, bundle_id)
        if claimed is not None:
            processed += 1
    return processed


async def process_bundle(db: Session, bundle_id: str) -> ResumeBundle | None:
    bundle = db.get(ResumeBundle, bundle_id)
    if bundle is None:
        raise AppError("RESUME_BUNDLE_NOT_FOUND", "简历包不存在。", 404)
    bundle = _reconcile_bundle_run(db, bundle)
    if bundle.status in {"ready", "degraded"}:
        return bundle
    token = claim_bundle_run(db, bundle_id)
    if token is None:
        db.refresh(bundle)
        _reconcile_bundle_run(db, bundle)
        return bundle if bundle.status in {"ready", "degraded", "generating", "failed"} else None
    inputs = _generation_inputs(db, bundle)
    db.commit()
    heartbeat_task = asyncio.create_task(_heartbeat_loop(db, bundle_id, token))
    try:
        result = await _compose_pair(inputs)
    except Exception as exc:
        heartbeat_task.cancel()
        await _cancel_task(heartbeat_task)
        _mark_bundle_failed(db, bundle_id, token, exc)
        db.commit()
        return db.get(ResumeBundle, bundle_id)
    heartbeat_task.cancel()
    await _cancel_task(heartbeat_task)
    bundle = _apply_pair_result(db, bundle_id, token, result)
    db.commit()
    if bundle is not None and bundle.status in {"ready", "degraded"}:
        from app.services.interview_guide_service import generate_guides_for_bundle

        await generate_guides_for_bundle(db, bundle)
        db.commit()
    return db.get(ResumeBundle, bundle_id)


async def _cancel_task(task: asyncio.Task) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _heartbeat_loop(db: Session, bundle_id: str, token: str) -> None:
    while True:
        await asyncio.sleep(15)
        try:
            if heartbeat_bundle_run(db, bundle_id, token):
                db.commit()
            else:
                db.rollback()
                return
        except Exception:
            db.rollback()
            logger.warning("resume_bundle_heartbeat_failed error_type=%s", "database")


def requeue_bundle(db: Session, user: User, bundle_id: str) -> ResumeBundle:
    bundle = owned_bundle(db, user, bundle_id)
    if bundle.status not in {"failed", "queued"}:
        raise AppError("RESUME_BUNDLE_NOT_RETRYABLE", "只有失败或排队中的简历包可以重试。", 409)
    run = db.get(ResumeBundleRun, bundle.id)
    if run is not None and run.status == "queued":
        return bundle
    if run is not None and run.status == "failed":
        retry_number = (run.retry_count or 0) + 1
        retry_key = f"resume-bundle-retry:{bundle.id}:{retry_number}"
        ledger = change(
            db,
            user_id=user.id,
            quota_type="resume",
            delta=-1,
            reason="重试生成双轨简历包",
            idempotency_key=retry_key,
            reference_type="resume_bundle",
            reference_id=bundle.id,
            request_hash=request_fingerprint(
                {
                    "operation": "resume_bundle.retry",
                    "bundle_id": bundle.id,
                    "retry_number": retry_number,
                }
            ),
        )
        if was_created(ledger):
            db.add(
                QuotaReservation(
                    ledger_id=ledger.id,
                    user_id=user.id,
                    quota_type=ledger.quota_type,
                    amount=-ledger.delta,
                    resource_type="resume_bundle",
                    resource_id=bundle.id,
                )
            )
    bundle.status = "queued"
    bundle.updated_at = now()
    if run is not None:
        run.status = "queued"
        run.phase = "queued"
        run.attempts = 0
        run.retry_count = (run.retry_count or 0) + 1
        run.lease_expires_at = None
        run.heartbeat_at = None
        run.last_error = ""
        run.public_error_code = ""
        run.updated_at = now()
    db.flush()
    return bundle


async def run_bundle_job(bundle_id: str) -> None:
    from app.database import make_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings

    engine = make_engine(get_settings().resolved_database_url())
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            await process_bundle(db, bundle_id)
            db.commit()
    finally:
        engine.dispose()


def _detached_fact(fact: ResumeFact) -> SimpleNamespace:
    return SimpleNamespace(
        id=fact.id,
        category=getattr(fact, "category", "") or "",
        label=getattr(fact, "label", "") or "",
        organization=getattr(fact, "organization", "") or "",
        role_title=getattr(fact, "role_title", "") or "",
        location=getattr(fact, "location", "") or "",
        start_date=getattr(fact, "start_date", "") or "",
        end_date=getattr(fact, "end_date", "") or "",
        value_json=deepcopy(fact.value_json or {}),
        source_text=getattr(fact, "source_text", "") or "",
        verification_status=getattr(fact, "verification_status", "") or "",
    )


def _generation_inputs(db: Session, bundle: ResumeBundle) -> dict:
    snapshot = bundle.facts_snapshot_json or {}
    run = db.get(ResumeBundleRun, bundle.id)
    task_snapshot = (run.input_snapshot_json or {}) if run is not None else {}
    fact_rows = snapshot.get("facts") or task_snapshot.get("facts") or []
    facts = [_fact_from_snapshot(row) for row in fact_rows if isinstance(row, dict)]
    target_snapshot = deepcopy(
        bundle.target_snapshot_json
        or task_snapshot.get("target")
        or {}
    )
    return {
        "bundle_id": bundle.id,
        "facts": facts,
        "draft_materials": list(snapshot.get("draft_materials") or task_snapshot.get("draft_materials") or []),
        "requirements": list(target_snapshot.get("requirements") or []),
        "headline": snapshot.get("headline") or task_snapshot.get("headline") or target_snapshot.get("title") or "目标岗位",
        "contact": deepcopy(snapshot.get("contact") or task_snapshot.get("contact") or {}),
        "job_id": snapshot.get("job_id") or task_snapshot.get("job_id"),
        "snapshot": deepcopy(bundle.template_snapshot_json or template_snapshot()),
    }


def _fact_from_snapshot(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(payload.get("id") or ""),
        category=str(payload.get("category") or ""),
        label=str(payload.get("label") or ""),
        organization=str(payload.get("organization") or ""),
        role_title=str(payload.get("role_title") or ""),
        location=str(payload.get("location") or ""),
        start_date=str(payload.get("start_date") or ""),
        end_date=str(payload.get("end_date") or ""),
        value_json={"text": str(payload.get("text") or "")},
        source_text=str(payload.get("source_text") or ""),
        verification_status=str(payload.get("verification_status") or ""),
        material_id=str(payload.get("material_id") or ""),
    )


def _mark_bundle_failed(db: Session, bundle_id: str, token: str, exc: Exception) -> None:
    bundle = db.scalar(
        select(ResumeBundle)
        .where(ResumeBundle.id == bundle_id)
        .execution_options(populate_existing=True)
    )
    run = _claimed_bundle_run(db, bundle_id, token)
    if bundle is None or run is None:
        return
    bundle.status = "failed"
    run.status = "failed"
    run.phase = "failed"
    run.public_error_code = "GENERATION_FAILED"
    run.last_error = _safe_error(f"{type(exc).__name__}")
    bundle.generation_metadata_json = {
        **(bundle.generation_metadata_json or {}),
        "error": "generation_failed",
        "error_message": _safe_error(type(exc).__name__),
    }
    _refund_bundle_reservation(db, bundle.id)
    run.updated_at = now()
    bundle.updated_at = now()
    db.flush()


def _bundle_reservation(db: Session, bundle_id: str) -> QuotaReservation | None:
    return db.scalar(
        select(QuotaReservation)
        .where(
            QuotaReservation.resource_type == "resume_bundle",
            QuotaReservation.resource_id == bundle_id,
        )
        .order_by(QuotaReservation.created_at.desc())
    )


def _complete_bundle_reservation(db: Session, bundle_id: str) -> None:
    reservation = _bundle_reservation(db, bundle_id)
    if reservation is not None and reservation.status == "pending":
        reservation.status = "completed"
        reservation.updated_at = now()


def _refund_bundle_reservation(db: Session, bundle_id: str) -> None:
    reservation = _bundle_reservation(db, bundle_id)
    if reservation is None or reservation.status != "pending":
        return
    ledger = db.get(QuotaLedger, reservation.ledger_id)
    if ledger is None or ledger.delta >= 0:
        reservation.status = "refunded"
        reservation.updated_at = now()
        return
    refund = change(
        db,
        user_id=reservation.user_id,
        quota_type=reservation.quota_type,
        delta=reservation.amount,
        reason="生成双轨简历包失败退回",
        idempotency_key=f"quota-refund:{reservation.ledger_id}",
        reference_type="quota_refund",
        reference_id=reservation.ledger_id,
        request_hash=request_fingerprint(
            {
                "operation": "quota.refund",
                "reservation_id": reservation.ledger_id,
                "delta": reservation.amount,
            }
        ),
    )
    if refund.reference_id == reservation.ledger_id or not was_created(refund):
        reservation.status = "refunded"
        reservation.updated_at = now()


async def _compose_pair(inputs: dict) -> dict:
    facts = inputs["facts"]
    draft_materials = inputs.get("draft_materials") or []
    requirements = inputs["requirements"]
    headline = inputs["headline"]
    contact = inputs["contact"]
    quality_gate_enabled = get_settings().resume_quality_gate_active()
    degraded = False
    repair_history: list[str] = []
    submittable, target, sub_source, tgt_source, write_error = await _write_pair(
        facts,
        requirements,
        headline=headline,
        contact=contact,
        draft_materials=draft_materials,
    )
    if sub_source == "fallback" or tgt_source == "fallback":
        degraded = True
        detail = ",".join(
            part
            for part in [
                f"submittable:{write_error}" if sub_source == "fallback" and write_error else "",
                f"target:{write_error}" if tgt_source == "fallback" and write_error else "",
            ]
            if part
        )
        repair_history.append(
            f"model_unavailable_local_fallback:{detail}" if detail else "model_unavailable_local_fallback"
        )

    sub_report = evaluate_version(
        content=submittable, facts=facts, requirements=requirements, mode="submittable"
    )
    tgt_report = evaluate_version(
        content=target, facts=facts, requirements=requirements, mode="target"
    )
    if quality_gate_enabled:
        need_sub_repair = not sub_report["hard_passed"]
        need_tgt_repair = not tgt_report["hard_passed"]
        if need_sub_repair or need_tgt_repair:
            if need_sub_repair:
                repair_history.append(
                    f"repair_submittable:{'|'.join(sub_report.get('issues') or ['content_gate_failed'])}"
                )
            if need_tgt_repair:
                repair_history.append(
                    f"repair_target:{'|'.join(tgt_report.get('issues') or ['content_gate_failed'])}"
                )
            repair_issues = list(sub_report.get("issues") or []) + list(tgt_report.get("issues") or [])
            submittable, target, sub_repair_source, tgt_repair_source, repair_error = await _write_pair(
                facts,
                requirements,
                headline=headline,
                contact=contact,
                draft_materials=draft_materials,
                current_submittable=submittable,
                current_target=target,
                repair_issues=repair_issues,
            )
            if sub_repair_source == "fallback":
                sub_source = "fallback"
                degraded = True
                if repair_error:
                    repair_history.append(f"repair_submittable_fallback:{repair_error}")
            if tgt_repair_source == "fallback":
                tgt_source = "fallback"
                degraded = True
                if repair_error:
                    repair_history.append(f"repair_target_fallback:{repair_error}")
            sub_report = evaluate_version(
                content=submittable, facts=facts, requirements=requirements, mode="submittable"
            )
            tgt_report = evaluate_version(
                content=target, facts=facts, requirements=requirements, mode="target"
            )

        if not sub_report["hard_passed"]:
            submittable = _fallback_version(
                facts, requirements, kind="submittable", headline=headline, contact=contact
            )
            sub_report = evaluate_version(
                content=submittable, facts=facts, requirements=requirements, mode="submittable"
            )
            degraded = True
            repair_history.append("deterministic_submittable_fallback")
        if not tgt_report["hard_passed"]:
            target = _fallback_version(
                facts, requirements, kind="target", headline=headline, contact=contact
            )
            tgt_report = evaluate_version(
                content=target, facts=facts, requirements=requirements, mode="target"
            )
            degraded = True
            repair_history.append("deterministic_target_fallback")

        if not sub_report["hard_passed"] or not tgt_report["hard_passed"]:
            return {
                "status": "failed",
                "repair_history": repair_history,
                "error": "hard_gates_failed",
                "submittable": submittable,
                "target": target,
                "sub_report": sub_report,
                "tgt_report": tgt_report,
                "sub_source": sub_source,
                "tgt_source": tgt_source,
            }
    else:
        # Debug mode bypasses only quality/layout/coverage failures. Invalid
        # provenance still blocks delivery so the switch cannot turn a foreign
        # source id into a deliverable resume.
        repair_history.append("quality_gate_disabled_local")
        if not report_guard_passed(sub_report) or not report_guard_passed(tgt_report):
            return {
                "status": "failed",
                "repair_history": repair_history,
                "error": "fact_guard_failed",
                "submittable": submittable,
                "target": target,
                "sub_report": sub_report,
                "tgt_report": tgt_report,
                "sub_source": sub_source,
                "tgt_source": tgt_source,
            }

    status = "degraded" if degraded else "ready"
    return {
        "status": status,
        "repair_history": repair_history,
        "submittable": submittable,
        "target": target,
        "sub_report": sub_report,
        "tgt_report": tgt_report,
        "sub_source": sub_source,
        "tgt_source": tgt_source,
        "degraded_reason": "；".join(
            reason
            for reason in [
                "本地开发已暂时关闭质量硬门禁，仅保留事实来源检查"
                if not quality_gate_enabled
                else "",
                "模型不可用或质量检查未完全通过，已使用确定性基础版本。"
                if degraded and quality_gate_enabled
                else "",
            ]
            if reason
        ),
        "job_id": inputs.get("job_id"),
        "snapshot": inputs.get("snapshot") or template_snapshot(),
    }


def _apply_pair_result(db: Session, bundle_id: str, token: str, result: dict) -> ResumeBundle | None:
    bundle = db.scalar(
        select(ResumeBundle)
        .where(ResumeBundle.id == bundle_id)
        .execution_options(populate_existing=True)
    )
    run = _claimed_bundle_run(db, bundle_id, token)
    if bundle is None:
        return None
    if run is None:
        return bundle
    quality_gate_enabled = get_settings().resume_quality_gate_active()
    reports = [result.get(name) or {} for name in ("sub_report", "tgt_report")]
    guards_passed = all(report_guard_passed(report) for report in reports)
    quality_passed = all(report.get("hard_passed") is True for report in reports)
    if result.get("status") in {"ready", "degraded"} and (
        not guards_passed or (quality_gate_enabled and not quality_passed)
    ):
        result = {
            **result,
            "status": "failed",
            "error": "fact_guard_failed" if not guards_passed else "hard_gates_failed",
        }
    repair_history = result.get("repair_history") or []
    if result.get("status") == "failed":
        bundle.status = "failed"
        bundle.generation_metadata_json = {
            "repair_history": repair_history,
            "error": result.get("error") or "hard_gates_failed",
            "error_message": "生成结果未通过硬门禁，请重试。",
        }
        if run is not None:
            run.status = "failed"
            run.phase = "failed"
            run.public_error_code = (
                "FACT_GUARD_FAILED"
                if result.get("error") == "fact_guard_failed"
                else "HARD_GATES_FAILED"
            )
            run.last_error = result.get("error") or "hard_gates_failed"
            run.updated_at = now()
        _refund_bundle_reservation(db, bundle.id)
        bundle.updated_at = now()
        db.flush()
        return bundle
    snapshot = result.get("snapshot") or bundle.template_snapshot_json or template_snapshot()
    job_id = result.get("job_id")
    _upsert_version(
        db,
        bundle,
        kind="submittable",
        content=result["submittable"],
        report=result["sub_report"],
        job_id=job_id,
        snapshot=snapshot,
        repair_history=repair_history,
    )
    _upsert_version(
        db,
        bundle,
        kind="target",
        content=result["target"],
        report=result["tgt_report"],
        job_id=job_id,
        snapshot=snapshot,
        repair_history=repair_history,
    )
    bundle.status = result["status"]
    bundle.generation_metadata_json = {
        "repair_history": repair_history,
        "degraded": bundle.status == "degraded",
        "degraded_reason": result.get("degraded_reason") or "",
        "quality_gate_bypassed": not get_settings().resume_quality_gate_active(),
        "writer": {
            "submittable": result.get("sub_source"),
            "target": result.get("tgt_source"),
        },
        "reviewer": {
            "submittable": (result.get("sub_report") or {}).get("reviewer"),
            "target": (result.get("tgt_report") or {}).get("reviewer"),
        },
    }
    if run is not None:
        run.status = bundle.status
        run.phase = "completed"
        run.last_error = ""
        run.public_error_code = ""
        run.result_resources_json = {
            "versions": {
                "submittable": next(
                    (row.id for row in db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == bundle.id, ResumeVersion.kind == "submittable"))),
                    None,
                ),
                "target": next(
                    (row.id for row in db.scalars(select(ResumeVersion).where(ResumeVersion.bundle_id == bundle.id, ResumeVersion.kind == "target"))),
                    None,
                ),
            }
        }
        run.updated_at = now()
    _complete_bundle_reservation(db, bundle.id)
    bundle.updated_at = now()
    db.flush()
    return bundle


async def _write_pair(
    facts,
    requirements,
    *,
    headline: str,
    contact: dict,
    draft_materials: list | None = None,
    current_submittable: dict | None = None,
    current_target: dict | None = None,
    repair_issues: list | None = None,
) -> tuple[dict, dict, str, str, str]:
    """One model call returns both resume kinds; IDs and order are assembled locally."""
    sub_fallback = _fallback_version(
        facts, requirements, kind="submittable", headline=headline, contact=contact
    )
    tgt_fallback = _fallback_version(
        facts, requirements, kind="target", headline=headline, contact=contact
    )
    mock = {
        "submittable": _schema_mock_content(
            current_submittable or sub_fallback,
            kind="submittable",
            headline=headline,
            contact=contact,
        ),
        "target": _schema_mock_content(
            current_target or tgt_fallback,
            kind="target",
            headline=headline,
            contact=contact,
        ),
    }
    try:
        structured, provider_name = await generate_structured(
            task="resume_rewrite",
            system_prompt=RESUME_REWRITE_PAIR_PROMPT,
            user_payload={
                "pair": True,
                "headline": headline,
                "contact": contact or {},
                "facts": [_fact_input(fact) for fact in facts],
                "draft_materials": list(draft_materials or []),
                "requirements": [
                    _requirement_input(item) for item in requirements if isinstance(item, dict)
                ],
                "current_submittable": current_submittable,
                "current_target": current_target,
                "repair_issues": list(repair_issues or []),
                "mock_response": mock,
            },
            response_model=ResumePairV3Output,
        )
        source = _writer_source(provider_name)
        submittable = _assemble_kind(
            structured.submittable.model_dump(),
            facts=facts,
            requirements=requirements,
            kind="submittable",
            headline=headline,
            contact=contact,
            current_content=current_submittable,
            fallback=sub_fallback,
        )
        target = _assemble_kind(
            structured.target.model_dump(),
            facts=facts,
            requirements=requirements,
            kind="target",
            headline=headline,
            contact=contact,
            current_content=current_target,
            fallback=tgt_fallback,
        )
        return submittable, target, source, source, ""
    except (ProviderError, AppError, Exception) as exc:
        error = str(getattr(exc, "code", "") or type(exc).__name__)
        if current_submittable is not None and current_target is not None:
            return (
                validate_content(deepcopy(current_submittable)),
                validate_content(deepcopy(current_target)),
                "fallback",
                "fallback",
                error,
            )
        return sub_fallback, tgt_fallback, "fallback", "fallback", error


def _assemble_kind(
    raw: dict,
    *,
    facts,
    requirements,
    kind: str,
    headline: str,
    contact: dict,
    current_content: dict | None,
    fallback: dict,
) -> dict:
    payload = dict(raw or {})
    payload["kind"] = kind
    payload["content_version"] = 3
    payload["factuality_policy"] = "ai_expansion"
    try:
        return assemble_model_copy(
            payload,
            facts=facts,
            requirements=requirements,
            kind=kind,
            headline=headline,
            contact=contact or {},
            current_content=current_content,
        )
    except (AppError, Exception):
        if current_content is not None:
            return validate_content(deepcopy(current_content))
        return fallback


async def _write_version(
    facts,
    requirements,
    *,
    kind: str,
    headline: str,
    contact: dict,
    current_content: dict | None = None,
    scope: str = "all",
    focus_bullet_id: str | None = None,
    focus_section_name: str | None = None,
    draft_materials: list | None = None,
    repair_issues: list | None = None,
) -> tuple[dict, str, str]:
    fallback = _fallback_version(
        facts, requirements, kind=kind, headline=headline, contact=contact
    )
    keep_current = current_content is not None
    mock_source = current_content if keep_current else fallback
    try:
        mock = _schema_mock_content(mock_source, kind=kind, headline=headline, contact=contact)
    except Exception:
        mock = _schema_mock_content(fallback, kind=kind, headline=headline, contact=contact)
    prompt = RESUME_REWRITE_SYSTEM_PROMPT
    if keep_current:
        prompt = f"{prompt} {RESUME_REWRITE_EXISTING_PROMPT}"
    try:
        structured, provider_name = await generate_structured(
            task="resume_rewrite",
            system_prompt=prompt,
            user_payload={
                "kind": kind,
                "headline": headline,
                "contact": contact or {},
                "facts": [_fact_input(fact) for fact in facts],
                "draft_materials": list(draft_materials or []),
                "requirements": [
                    _requirement_input(item) for item in requirements if isinstance(item, dict)
                ],
                "scope": scope,
                "focus_bullet_id": focus_bullet_id,
                "focus_section_name": focus_section_name,
                "current_content": current_content,
                "repair_issues": list(repair_issues or []),
                "mock_response": mock,
            },
            response_model=ResumeStructuredV3Output,
        )
        content = assemble_model_copy(
            structured.model_dump(),
            facts=facts,
            requirements=requirements,
            kind=kind,
            headline=headline,
            contact=contact or {},
            current_content=current_content,
        )
        return content, _writer_source(provider_name), ""
    except (ProviderError, AppError, Exception) as exc:
        error = str(getattr(exc, "code", "") or type(exc).__name__)
        if keep_current:
            return validate_content(deepcopy(current_content)), "fallback", error
        return fallback, "fallback", error


def _schema_mock_content(content: dict, *, kind: str, headline: str, contact: dict) -> dict:
    payload = {
        "content_version": 3,
        "kind": content.get("kind") or kind,
        "headline": content.get("headline") or headline,
        "contact": content.get("contact") or contact or {},
        "sections": content.get("sections") or [],
        "excluded_gaps": content.get("excluded_gaps") or [],
    }
    return ResumeStructuredV3Output.model_validate(payload).model_dump()


def _restore_bullet_ids(content: dict, previous: dict | None) -> dict:
    if not previous:
        return content
    previous_rows = list(iter_bullets(previous))
    current_rows = list(iter_bullets(content))
    if len(previous_rows) != len(current_rows):
        return content
    for (_section, _item, old_bullet), (_new_section, _new_item, new_bullet) in zip(
        previous_rows, current_rows
    ):
        if old_bullet.get("id"):
            new_bullet["id"] = old_bullet["id"]
            new_bullet["locked"] = bool(old_bullet.get("locked"))
    return content


def _fallback_version(facts, requirements, *, kind: str, headline: str, contact: dict) -> dict:
    grouped: dict[str, list] = {name: [] for name in SECTION_ORDER}
    buckets: dict[tuple[str, str, str, str], dict] = {}
    for fact in facts:
        section = CATEGORY_SECTIONS.get(getattr(fact, "category", ""), "项目/科研/竞赛")
        text = _fact_text(fact)
        if not text:
            continue
        bullet = normalize_bullet(
            {
                "id": new_bullet_id(),
                "text": text[:120],
                "source_fact_ids": [fact.id],
                "source_target_ids": [],
                "requirement_ids": [],
                "achieved": True,
                "locked": False,
                "new_claims": [],
            }
        )
        org = _usable_fallback_org(getattr(fact, "organization", ""))
        role = str(getattr(fact, "role_title", "") or "").strip()
        start = str(getattr(fact, "start_date", "") or "").strip()
        key = (section, org, role, start)
        item = buckets.get(key)
        if item is None:
            item = {
                "organization": org,
                "role_title": role,
                "location": str(getattr(fact, "location", "") or ""),
                "start_date": start,
                "end_date": str(getattr(fact, "end_date", "") or ""),
                "bullets": [],
            }
            buckets[key] = item
            grouped.setdefault(section, []).append(item)
        item["bullets"].append(bullet)
    excluded = []
    if kind == "target" or not facts:
        fact_text = " ".join(
            str((fact.value_json or {}).get("text") or "") for fact in facts
        )
        future_items = []
        for requirement in requirements:
            text = str(requirement.get("text") or "")
            if not text or text in fact_text:
                continue
            if requirement.get("priority") != "high" and future_items:
                continue
            future_items.append(
                {
                    "organization": "",
                    "role_title": "目标补齐",
                    "location": "",
                    "start_date": "",
                    "end_date": "",
                    "bullets": [
                        normalize_bullet(
                            {
                                "id": new_bullet_id(),
                                "text": text[:120],
                                "source_fact_ids": [],
                                "source_target_ids": [requirement["id"]],
                                "requirement_ids": [requirement["id"]],
                                "achieved": False,
                                "locked": False,
                                "new_claims": [],
                            },
                            default_achieved=False,
                        )
                    ],
                }
            )
        if not future_items and not facts:
            future_items.append(
                {
                    "organization": "",
                    "role_title": "待补充经历",
                    "location": "",
                    "start_date": "",
                    "end_date": "",
                    "bullets": [
                        normalize_bullet(
                            {
                                "id": new_bullet_id(),
                                "text": "围绕目标岗位补充一段相关经历描述。",
                                "source_fact_ids": [],
                                "source_target_ids": [],
                                "requirement_ids": [],
                                "achieved": False,
                                "locked": False,
                                "new_claims": ["待结合本人经历调整的经历描述"],
                                "verification_status": "ai_generated",
                            },
                            default_achieved=False,
                        )
                    ],
                }
            )
        if future_items:
            grouped["项目/科研/竞赛"].extend(future_items)
        cited_requirements = {
            req_id
            for item in sum(grouped.values(), [])
            for bullet in item.get("bullets") or []
            for req_id in bullet.get("requirement_ids") or []
        }
        for requirement in requirements:
            text = str(requirement.get("text") or "")
            if (
                requirement.get("priority") == "high"
                and requirement.get("id") not in cited_requirements
                and text
                and text not in fact_text
            ):
                excluded.append(text)
    sections = [
        {"name": name, "presentation": "tags" if name == "技能" else "items", "items": grouped[name]}
        for name in SECTION_ORDER
        if grouped.get(name)
    ]
    return validate_content(
        {
            "content_version": 3,
            "factuality_policy": "ai_expansion",
            "kind": kind,
            "headline": headline,
            "contact": contact or {},
            "sections": sections,
            "excluded_gaps": excluded,
        }
    )


def _omit_ungrounded_future(content: dict) -> dict:
    for section in content.get("sections") or []:
        items = []
        for item in section.get("items") or []:
            bullets = [
                bullet
                for bullet in item.get("bullets") or []
                if bullet.get("achieved") is not False
                or bullet.get("requirement_ids")
                or bullet.get("source_target_ids")
            ]
            if bullets:
                items.append({**item, "bullets": bullets})
        section["items"] = items
    content["sections"] = [section for section in content["sections"] if section.get("items")]
    return content


def _upsert_version(
    db: Session,
    bundle: ResumeBundle,
    *,
    kind: str,
    content: dict,
    report: dict,
    job_id: str | None,
    snapshot: dict,
    repair_history: list[str],
) -> ResumeVersion:
    content = validate_content(content)
    digest = request_fingerprint(content)
    report = {
        **report,
        "repair_history": repair_history,
        "content_hash": digest,
        "review_version": "v3-quality-1",
    }
    row = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.bundle_id == bundle.id, ResumeVersion.kind == kind
        )
    )
    if row is None:
        row = ResumeVersion(
            id=uid(),
            user_id=bundle.user_id,
            base_resume_id=bundle.base_resume_id,
            job_id=job_id,
            bundle_id=bundle.id,
            target_profile_id=bundle.target_profile_id,
            title=f"{content.get('headline') or '简历'} · {'求职简历' if kind == 'submittable' else '蓝图 Plus'}",
            kind=kind,
            content_json=content,
            traceability_json={"items": report.get("guard", {}).get("items") or []},
        )
        db.add(row)
    row.content_json = content
    row.traceability_json = {"items": report.get("guard", {}).get("items") or []}
    row.guard_status = "passed" if report_guard_passed(report) else "blocked"
    row.unachieved_count = int(report.get("unachieved_count") or 0)
    row.quality_report_json = _public_quality_report(
        report, quality_gate_enabled=get_settings().resume_quality_gate_active()
    )
    row.content_hash = digest
    row.template_snapshot_json = snapshot
    row.review_status = "draft"
    row.updated_at = now()
    db.flush()
    return row


def _public_quality_report(report: dict, *, quality_gate_enabled: bool | None = None) -> dict:
    if quality_gate_enabled is None:
        quality_gate_enabled = get_settings().resume_quality_gate_active()
    status = quality_report_status(report, gate_enabled=quality_gate_enabled)
    return {
        "warnings": report.get("warnings") or [],
        "status": status,
        "hard_passed": report.get("hard_passed"),
        "guard_status": "passed" if report_guard_passed(report) else "blocked",
        "quality_gate_enabled": quality_gate_enabled,
        "quality_gate_bypassed": status == "bypassed",
        "issues": report.get("issues") or [],
        "layout_warnings": report.get("layout_warnings") or [],
        "uncovered_requirements": report.get("uncovered_requirements") or [],
        "dimensions": report.get("dimensions") or {},
        "repair_history": report.get("repair_history") or [],
        "review_version": report.get("review_version"),
        "content_hash": report.get("content_hash"),
        "unachieved_count": report.get("unachieved_count") or 0,
        "reviewer": report.get("reviewer") or "deterministic",
        "reviewer_note": report.get("reviewer_note") or "",
    }


async def regenerate_scope(
    db: Session,
    user: User,
    bundle_id: str,
    *,
    version_id: str,
    scope: str,
    bullet_id: str | None = None,
    section_name: str | None = None,
) -> ResumeVersion:
    bundle = owned_bundle(db, user, bundle_id)
    version = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id,
            ResumeVersion.bundle_id == bundle.id,
            ResumeVersion.user_id == user.id,
        )
    )
    if not version:
        raise AppError("RESUME_VERSION_NOT_FOUND", "简历版本不存在。", 404)
    content = deepcopy(version.content_json or {})
    facts = [
        db.get(ResumeFact, fact_id)
        for fact_id in (bundle.facts_snapshot_json or {}).get("ids") or []
    ]
    facts = [fact for fact in facts if fact is not None]
    requirements = list((bundle.target_snapshot_json or {}).get("requirements") or [])
    draft_materials = list((bundle.facts_snapshot_json or {}).get("draft_materials") or [])
    locked_ids = {
        bullet.get("id")
        for _s, _i, bullet in iter_bullets(content)
        if bullet.get("locked")
    }
    headline = str(content.get("headline") or "")
    contact = content.get("contact") or {}
    if scope == "bullet" and bullet_id:
        if bullet_id in locked_ids:
            raise AppError("RESUME_BULLET_LOCKED", "已锁定要点不能重生成。", 409)
        source = await _replace_bullet_from_writer(
            content,
            facts=facts,
            requirements=requirements,
            kind=version.kind,
            headline=headline,
            contact=contact,
            bullet_id=bullet_id,
        )
        if source is None:
            raise AppError(
                "RESUME_REGENERATION_UNAVAILABLE",
                "模型暂时不可用，本次没有替换要点，请稍后重试。",
                503,
                {"retryable": True},
            )
    elif scope == "section" and section_name:
        rewritten, source, _error = await _write_version(
            facts,
            requirements,
            kind=version.kind,
            headline=headline,
            contact=contact,
            current_content=content,
            scope="section",
            focus_section_name=section_name,
            draft_materials=draft_materials,
        )
        if source == "fallback":
            raise AppError(
                "RESUME_REGENERATION_UNAVAILABLE",
                "模型暂时不可用，本次没有替换分区，请稍后重试。",
                503,
                {"retryable": True},
            )
        _replace_section(content, rewritten, section_name, locked_ids)
    elif scope == "all":
        rewritten, source, _error = await _write_version(
            facts,
            requirements,
            kind=version.kind,
            headline=headline,
            contact=contact,
            current_content=content,
            scope="all",
            draft_materials=draft_materials,
        )
        if source == "fallback":
            raise AppError(
                "RESUME_REGENERATION_UNAVAILABLE",
                "模型暂时不可用，本次没有替换简历，请稍后重试。",
                503,
                {"retryable": True},
            )
        content = _merge_locked(rewritten, content, locked_ids)
    else:
        raise AppError("REGENERATE_SCOPE_INVALID", "只支持按要点、分区或整份重生成。", 422)
    report = await evaluate_version_with_critic(
        content=content, facts=facts, requirements=requirements, mode=version.kind
    )
    snapshot = version.template_snapshot_json or bundle.template_snapshot_json
    old_hash = version.content_hash
    updated = _upsert_version(
        db,
        bundle,
        kind=version.kind,
        content=content,
        report=report,
        job_id=version.job_id,
        snapshot=snapshot,
        repair_history=["selective_regenerate"],
    )
    if updated.content_hash != old_hash:
        _stale_guides(db, updated)
    return updated


async def _replace_bullet_from_writer(content, *, facts, requirements, kind, headline, contact, bullet_id):
    original = None
    for section, item, bullet in iter_bullets(content):
        if bullet.get("id") == bullet_id:
            original = (section, item, bullet)
            break
    if original is None:
        raise AppError("RESUME_BULLET_NOT_FOUND", "要点不存在。", 404)
    _section, item, bullet = original
    fact_ids = {str(value) for value in bullet.get("source_fact_ids") or []}
    req_ids = {
        str(value)
        for value in (bullet.get("requirement_ids") or []) + (bullet.get("source_target_ids") or [])
    }
    scoped_facts = [fact for fact in facts if str(fact.id) in fact_ids] if fact_ids else list(facts)
    scoped_requirements = (
        [requirement for requirement in requirements if str(requirement.get("id") or "") in req_ids]
        if req_ids
        else list(requirements)
    )
    mock = {
        "text": _mock_rewritten_text(str(bullet.get("text") or "")),
        "source_fact_ids": list(bullet.get("source_fact_ids") or []),
        "source_target_ids": list(bullet.get("source_target_ids") or []),
        "requirement_ids": list(bullet.get("requirement_ids") or []),
        "achieved": bool(bullet.get("achieved")),
        "new_claims": list(bullet.get("new_claims") or []),
        "verification_status": bullet.get("verification_status") or "ai_generated",
    }
    try:
        structured, provider = await generate_structured(
            task="resume_rewrite",
            system_prompt=f"{RESUME_REWRITE_SYSTEM_PROMPT} {RESUME_REWRITE_EXISTING_PROMPT}",
            user_payload={
                "scope": "bullet",
                "kind": kind,
                "headline": headline,
                "contact": contact or {},
                "current_bullet": deepcopy(bullet),
                "experience": {
                    "organization": item.get("organization"),
                    "role_title": item.get("role_title"),
                    "location": item.get("location"),
                    "start_date": item.get("start_date"),
                    "end_date": item.get("end_date"),
                },
                "facts": [_fact_input(fact) for fact in scoped_facts],
                "requirements": [
                    _requirement_input(requirement)
                    for requirement in scoped_requirements
                    if isinstance(requirement, dict)
                ],
                "mock_response": mock,
            },
            response_model=ResumeBulletRewriteOutput,
        )
        incoming = normalize_bullet(
            {
                **bullet,
                "id": bullet_id,
                "text": structured.text,
                "new_claims": list(structured.new_claims or bullet.get("new_claims") or []),
                "verification_status": structured.verification_status
                or bullet.get("verification_status")
                or "ai_generated",
                "locked": bool(bullet.get("locked")),
            },
            default_achieved=kind == "submittable",
        )
        if incoming.get("new_claims") or incoming.get("verification_status") == "ai_generated":
            incoming["verification_status"] = "ai_generated"
            incoming["achieved"] = False
    except (ProviderError, AppError, Exception):
        return None
    incoming["id"] = bullet_id
    incoming["locked"] = bool(bullet.get("locked"))
    if fact_ids:
        incoming["source_fact_ids"] = list(fact_ids)
    if req_ids:
        incoming["requirement_ids"] = list(req_ids)
        incoming["source_target_ids"] = list(req_ids)
    bullets = item.get("bullets") or []
    for index, current in enumerate(bullets):
        if current.get("id") == bullet_id:
            bullets[index] = incoming
            break
    return "fallback" if provider == "mock_fallback" else "model"


def _mock_rewritten_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return "补充岗位相关的具体行动和结果。"
    if value.endswith("，并写清个人承担的步骤。"):
        return value
    return f"{value.rstrip('。.')}，并写清个人承担的步骤。"[:80]


def _select_rewritten_bullet(rewritten, *, original, original_index, original_count, fact_ids, req_ids):
    candidates = visible_bullets(rewritten)
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.get("id") and candidate.get("id") == original.get("id"):
            return candidate
    for candidate in candidates:
        candidate_facts = {str(value) for value in candidate.get("source_fact_ids") or []}
        candidate_reqs = {
            str(value)
            for value in (candidate.get("requirement_ids") or [])
            + (candidate.get("source_target_ids") or [])
        }
        if fact_ids and candidate_facts & fact_ids:
            return candidate
        if req_ids and candidate_reqs & req_ids:
            return candidate
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == original_count and 0 <= original_index < len(candidates):
        return candidates[original_index]
    return None


def _replace_section(content, replacement, section_name, locked_ids):
    original = next(
        (section for section in content.get("sections") or [] if section.get("name") == section_name),
        None,
    )
    incoming = next(
        (section for section in replacement.get("sections") or [] if section.get("name") == section_name),
        None,
    )
    if incoming is None:
        return
    if original is not None:
        incoming = _merge_locked(
            {"sections": [deepcopy(incoming)], "kind": content.get("kind")},
            {"sections": [original]},
            locked_ids,
        )["sections"][0]
    for index, section in enumerate(content.get("sections") or []):
        if section.get("name") == section_name:
            content["sections"][index] = incoming


def _merge_locked(replacement, original, locked_ids):
    if not locked_ids:
        return replacement
    locked_records = []
    for section_index, section in enumerate(original.get("sections") or []):
        for item_index, item in enumerate(section.get("items") or []):
            for bullet_index, bullet in enumerate(item.get("bullets") or []):
                if bullet.get("id") in locked_ids:
                    locked_records.append(
                        {
                            "section": section.get("name"),
                            "section_index": section_index,
                            "item_index": item_index,
                            "bullet_index": bullet_index,
                            "item": {
                                "organization": item.get("organization"),
                                "role_title": item.get("role_title"),
                                "location": item.get("location"),
                                "start_date": item.get("start_date"),
                                "end_date": item.get("end_date"),
                            },
                            "bullet": deepcopy(bullet),
                        }
                    )
    if not locked_records:
        return replacement

    def same_item(left: dict, right: dict) -> bool:
        return all(
            left.get(field) == right.get(field)
            for field in ("organization", "role_title", "location", "start_date", "end_date")
        )

    for section in replacement.get("sections") or []:
        for item in section.get("items") or []:
            item["bullets"] = [
                bullet
                for bullet in item.get("bullets") or []
                if bullet.get("id") not in locked_ids
                and not any(
                    record["bullet"].get("text") == bullet.get("text")
                    and same_item(record["item"], item)
                    for record in locked_records
                )
            ]
    replacement["sections"] = [
        section
        for section in replacement.get("sections") or []
        if any(item.get("bullets") for item in section.get("items") or [])
    ]
    for record in locked_records:
        section = next(
            (
                item
                for item in replacement.get("sections") or []
                if item.get("name") == record["section"]
            ),
            None,
        )
        if section is None:
            section = {
                "name": record["section"],
                "presentation": "items",
                "items": [],
            }
            sections = replacement.setdefault("sections", [])
            insert_section_at = min(record["section_index"], len(sections))
            sections.insert(insert_section_at, section)
        items = section.setdefault("items", [])
        item_index = min(record["item_index"], len(items))
        item = items[item_index] if item_index < len(items) else None
        if item is None or not same_item(item, record["item"]):
            item = {**record["item"], "bullets": []}
            items.insert(item_index, item)
        bullets = item.setdefault("bullets", [])
        insert_at = min(record["bullet_index"], len(bullets))
        bullets.insert(insert_at, record["bullet"])
    order = {name: index for index, name in enumerate(SECTION_ORDER)}
    replacement["sections"] = sorted(
        replacement.get("sections") or [],
        key=lambda section: order.get(str(section.get("name") or ""), 99),
    )
    return replacement


def _stale_guides(db: Session, version: ResumeVersion) -> None:
    guides = list(
        db.scalars(
            select(InterviewGuide).where(InterviewGuide.resume_version_id == version.id)
        )
    )
    for guide in guides:
        guide.status = "stale"
        guide.updated_at = now()


def stale_guides_for_version(db: Session, version: ResumeVersion) -> None:
    """Mark all guides bound to an edited version as stale."""
    _stale_guides(db, version)
