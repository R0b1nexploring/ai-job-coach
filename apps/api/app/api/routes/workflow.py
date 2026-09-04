import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, StrictStr, field_validator
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user
from app.errors import AppError
from app.models.entities import (
    Application,
    ApplicationChannel,
    ApplicationEvent,
    AuditLog,
    CapabilityTarget,
    CapabilityTargetRun,
    Interview,
    Job,
    Match,
    Notification,
    Order,
    Package,
    QuotaLedger,
    QuotaReservation,
    Resume,
    ResumeFact,
    ResumeVersion,
    StorageDeletionTask,
    User,
    UserProfile,
)
from app.providers.llm.schemas import ResumeContentOutput
from app.providers.storage.local import LocalStorage
from app.services.capability_service import build_targets, ensure_match_targets
from app.services.experience_service import confirmed_facts_for_generation
from app.services.job_access import owned_job_clause, visible_job
from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html
from app.services.interview_generator import generate_guarded_interview
from app.services.quota_service import (
    balance,
    change,
    request_fingerprint,
    was_created,
)
from app.services.report_service import weekly_report
from app.services.resume_generator import (
    MAX_RESUME_LINES,
    estimate_resume_lines,
    evaluate_resume_content,
    generate_guarded_resume,
)
from app.services.storage_cleanup import enqueue_file_deletions

from .common import dump, listed

router = APIRouter(prefix="/api", tags=["workflow"])
logger = logging.getLogger(__name__)
MAX_INTERVIEW_ANSWERS = 50
MAX_INTERVIEW_ANSWER_CHARS = 5000
CAPABILITY_TARGET_RUN_TIMEOUT = timedelta(minutes=15)


class CapabilityTargetPatch(BaseModel):
    status: Literal["pending", "in_progress", "achieved", "abandoned"]
    evidence_text: str = Field(default="", max_length=10000)


@router.post("/matches/{match_id}/capability-targets", status_code=201)
async def create_capability_targets(
    match_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    match = db.scalar(select(Match).where(Match.id == match_id, Match.user_id == user.id))
    if not match:
        raise AppError("MATCH_NOT_FOUND", "匹配报告不存在。", 404)
    existing = list(
        db.scalars(
            select(CapabilityTarget)
            .where(
                CapabilityTarget.match_id == match.id,
                CapabilityTarget.user_id == user.id,
            )
            .order_by(CapabilityTarget.created_at)
        )
    )
    if existing:
        return {
            "items": [dump(row) for row in existing],
            "total": len(existing),
            "provider": "existing",
        }
    generated_before = db.scalar(
        select(AuditLog.id).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action == "capability_targets.created",
            AuditLog.entity_type == "match",
            AuditLog.entity_id == match.id,
        )
    )
    if generated_before:
        return {"items": [], "total": 0, "provider": "existing"}
    job = visible_job(db, user, match.job_id)
    if not job:
        raise AppError("JOB_NOT_FOUND", "岗位不存在。", 404)
    facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == match.resume_id,
                ResumeFact.user_id == user.id,
            )
        )
    )
    # End the validation/read transaction before atomically claiming the run.
    # This avoids SQLite's unsupported read-to-write lock upgrade race.
    db.commit()
    run_hash = request_fingerprint(
        {"operation": "capability_targets.create", "match_id": match.id}
    )
    claim_token = str(uuid.uuid4())
    candidate = CapabilityTargetRun(
        match_id=match.id,
        user_id=user.id,
        status="pending",
        claim_token=claim_token,
        request_hash=run_hash,
    )
    try:
        # The INSERT is the first statement in this transaction. Its primary
        # key is the cross-process generation lock.
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        run = candidate
        db.commit()
    except IntegrityError:
        run = db.get(CapabilityTargetRun, match.id)
        if run is None:
            raise
    if run.user_id != user.id or (run.request_hash and run.request_hash != run_hash):
        raise AppError(
            "CAPABILITY_TARGET_RUN_CONFLICT",
            "该匹配报告的学习目标生成记录不一致。",
            409,
        )
    if run.claim_token != claim_token:
        if run.status == "completed":
            completed = list(
                db.scalars(
                    select(CapabilityTarget)
                    .where(
                        CapabilityTarget.match_id == match.id,
                        CapabilityTarget.user_id == user.id,
                    )
                    .order_by(CapabilityTarget.created_at)
                )
            )
            return {
                "items": [dump(row) for row in completed],
                "total": len(completed),
                "provider": run.provider or "existing",
            }
        takeover = update(CapabilityTargetRun).where(
            CapabilityTargetRun.match_id == match.id,
            CapabilityTargetRun.user_id == user.id,
            CapabilityTargetRun.claim_token == run.claim_token,
            CapabilityTargetRun.status == run.status,
        )
        if run.status == "pending":
            takeover = takeover.where(
                CapabilityTargetRun.updated_at
                < datetime.now(timezone.utc) - CAPABILITY_TARGET_RUN_TIMEOUT
            )
        elif run.status != "failed":
            raise AppError(
                "CAPABILITY_TARGET_GENERATION_IN_PROGRESS",
                "学习目标正在生成，请稍后重试。",
                409,
            )
        # The failed INSERT recovery loaded the winner. End that read
        # transaction before trying the takeover CAS on SQLite.
        db.commit()
        claimed = db.execute(
            takeover.values(
                status="pending",
                claim_token=claim_token,
                request_hash=run_hash,
                provider="",
                last_error="",
                updated_at=datetime.now(timezone.utc),
            ).execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise AppError(
                "CAPABILITY_TARGET_GENERATION_IN_PROGRESS",
                "学习目标正在生成，请稍后重试。",
                409,
            )
        db.commit()

    try:
        values, provider_name = await build_targets(match, job, facts)
        completed = db.execute(
            update(CapabilityTargetRun)
            .where(
                CapabilityTargetRun.match_id == match.id,
                CapabilityTargetRun.user_id == user.id,
                CapabilityTargetRun.status == "pending",
                CapabilityTargetRun.claim_token == claim_token,
            )
            .values(
                status="completed",
                provider=provider_name,
                last_error="",
                updated_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if completed.rowcount != 1:
            db.rollback()
            raise AppError(
                "CAPABILITY_TARGET_GENERATION_SUPERSEDED",
                "本次学习目标生成已被新的请求接管，请重新获取结果。",
                409,
            )
        rows = []
        for value in values:
            row = CapabilityTarget(
                user_id=user.id,
                job_id=job.id,
                match_id=match.id,
                **value,
            )
            db.add(row)
            rows.append(row)
        db.flush()
        db.add(
            AuditLog(
                actor_user_id=user.id,
                action="capability_targets.created",
                entity_type="match",
                entity_id=match.id,
                metadata_json={"count": len(rows), "provider": provider_name},
            )
        )
        db.commit()
        return {
            "items": [dump(row) for row in rows],
            "total": len(rows),
            "provider": provider_name,
        }
    except BaseException as exc:
        db.rollback()
        try:
            failed = db.execute(
                update(CapabilityTargetRun)
                .where(
                    CapabilityTargetRun.match_id == match.id,
                    CapabilityTargetRun.status == "pending",
                    CapabilityTargetRun.claim_token == claim_token,
                )
                .values(
                    status="failed",
                    last_error=type(exc).__name__[:200],
                    updated_at=datetime.now(timezone.utc),
                )
                .execution_options(synchronize_session=False)
            )
            if failed.rowcount:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            logger.warning("Failed to record capability target generation failure")
        raise


@router.get("/capability-targets")
async def capability_targets(
    job_id: str | None = None,
    status: Literal["pending", "in_progress", "achieved", "abandoned"] | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    statement = select(CapabilityTarget).where(CapabilityTarget.user_id == user.id)
    if job_id:
        statement = statement.where(CapabilityTarget.job_id == job_id)
    if status:
        statement = statement.where(CapabilityTarget.status == status)
    rows = list(db.scalars(statement.order_by(CapabilityTarget.created_at.desc())))
    return listed([dump(row) for row in rows])


@router.patch("/capability-targets/{target_id}")
async def update_capability_target(
    target_id: str,
    data: CapabilityTargetPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    target = db.scalar(
        select(CapabilityTarget).where(
            CapabilityTarget.id == target_id,
            CapabilityTarget.user_id == user.id,
        )
    )
    if not target:
        raise AppError("CAPABILITY_TARGET_NOT_FOUND", "学习目标不存在。", 404)
    if target.status == "achieved":
        if data.status == "achieved":
            return dump(target)
        raise AppError("CAPABILITY_TARGET_FINAL", "已达成目标不能回退状态。", 409)
    if data.status == "achieved":
        evidence_text = data.evidence_text.strip()
        if not evidence_text:
            raise AppError("CAPABILITY_EVIDENCE_REQUIRED", "标记达成时必须填写产出物证据。", 422)
        match = db.scalar(
            select(Match).where(
                Match.id == target.match_id,
                Match.user_id == user.id,
            )
        )
        if not match:
            raise AppError("MATCH_NOT_FOUND", "目标关联的匹配报告不存在。", 409)
        fact = ResumeFact(
            resume_id=match.resume_id,
            user_id=user.id,
            category=target.category,
            label=target.requirement[:200],
            value_json={"text": f"{target.deliverable}\n证据：{evidence_text}"},
            organization="",
            provenance="learned",
            source_text=evidence_text,
            source_location="学习目标证据",
            verification_status="user_confirmed",
            created_by=user.id,
            confirmed_at=datetime.now(timezone.utc),
        )
        db.add(fact)
        db.flush()
        target.status = "achieved"
        target.evidence_text = evidence_text
        target.achieved_fact_id = fact.id
        target.achieved_at = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                actor_user_id=user.id,
                action="capability_target.achieved",
                entity_type="capability_target",
                entity_id=target.id,
                metadata_json={"achieved_fact_id": fact.id},
            )
        )
    else:
        allowed = {
            "pending": {"pending", "in_progress", "abandoned"},
            "in_progress": {"pending", "in_progress", "abandoned"},
            "abandoned": {"pending", "abandoned"},
        }
        if data.status not in allowed.get(target.status, set()):
            raise AppError("INVALID_TARGET_STATUS", "该学习目标状态不能这样变更。", 409)
        target.status = data.status
    db.commit()
    return dump(target)


class VersionIn(BaseModel):
    base_resume_id: str
    job_id: str
    match_id: str
    kind: Literal["target", "submittable"] = "submittable"


def _idempotent_resource(
    db: Session,
    *,
    ledger: QuotaLedger,
    reference_type: str,
    model,
    user_id: str,
):
    """Resolve a ledger won by another request without creating a second resource."""
    if ledger.reference_type != reference_type or not ledger.reference_id:
        raise AppError(
            "IDEMPOTENCY_KEY_REUSED",
            "该幂等键已用于其他额度操作，请更换后重试。",
            409,
        )
    existing = db.scalar(
        select(model).where(model.id == ledger.reference_id, model.user_id == user_id)
    )
    if not existing:
        raise AppError(
            "IDEMPOTENCY_RESULT_UNAVAILABLE",
            "相同请求仍在处理中，请稍后使用同一幂等键重试。",
            409,
        )
    return existing


def _refund_quota_reservation(db: Session, ledger: QuotaLedger) -> None:
    """Compensate a committed pre-call debit without masking the root error."""
    db.rollback()
    try:
        refund_key = f"quota-refund:{ledger.id}"
        change(
            db,
            user_id=ledger.user_id,
            quota_type=ledger.quota_type,
            delta=-ledger.delta,
            reason=f"{ledger.reason}失败退回",
            idempotency_key=refund_key,
            reference_type="quota_refund",
            reference_id=ledger.id,
            request_hash=request_fingerprint(
                {
                    "operation": "quota.refund",
                    "reservation_id": ledger.id,
                    "delta": -ledger.delta,
                }
            ),
        )
        reservation = db.get(QuotaReservation, ledger.id)
        if reservation is not None:
            reservation.status = "refunded"
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to compensate quota reservation %s", ledger.id)


@router.post("/resume-versions", status_code=201)
async def create_version(
    data: VersionIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    resume = db.scalar(
        select(Resume).where(
            Resume.id == data.base_resume_id, Resume.user_id == user.id, Resume.deleted_at.is_(None)
        )
    )
    job = visible_job(db, user, data.job_id)
    match = db.scalar(
        select(Match).where(
            Match.id == data.match_id,
            Match.user_id == user.id,
            Match.resume_id == data.base_resume_id,
            Match.job_id == data.job_id,
        )
    )
    if not all([resume, job, match]):
        raise AppError("RESOURCE_NOT_FOUND", "简历、岗位或匹配报告不存在。", 404)
    if not resume.facts_confirmed_at:
        raise AppError("RESUME_FACTS_NOT_CONFIRMED", "请先确认简历事实库后再生成定制版本。", 409)
    confirmed_facts = confirmed_facts_for_generation(db, user, resume)
    targets = (
        ensure_match_targets(db, user, match, job)
        if data.kind == "target"
        else []
    )
    key = idempotency_key or f"resume-version:{user.id}:{uuid.uuid4()}"
    payload_hash = request_fingerprint(
        {"operation": "resume_version.create", **data.model_dump(mode="json")}
    )
    db.commit()
    ledger = change(
        db,
        user_id=user.id,
        quota_type="resume",
        delta=-1,
        reason="生成定制简历",
        idempotency_key=key,
        reference_type="resume_version",
        reference_id=str(uuid.uuid4()),
        request_hash=payload_hash,
    )
    if not was_created(ledger):
        return dump(
            _idempotent_resource(
                db,
                ledger=ledger,
                reference_type="resume_version",
                model=ResumeVersion,
                user_id=user.id,
            )
        )
    db.add(
        QuotaReservation(
            ledger_id=ledger.id,
            user_id=user.id,
            quota_type=ledger.quota_type,
            amount=-ledger.delta,
            resource_type="resume_version",
            resource_id=ledger.reference_id,
        )
    )
    # Commit the unique claim and debit before invoking the external model. A
    # concurrent replay now observes the claim and never duplicates the call.
    db.commit()
    try:
        generated = await generate_guarded_resume(
            confirmed_facts,
            job,
            targets,
            kind=data.kind,
            contact=resume.contact_json,
            match=match,
        )
        content = generated["content"]
        provider_name = generated["provider"]
        evaluation = generated["evaluation"]
        fallback_used = generated["fallback_used"]
        fallback_reason = generated["fallback_reason"]
        version = ResumeVersion(
            id=ledger.reference_id,
            user_id=user.id,
            base_resume_id=resume.id,
            job_id=job.id,
            match_id=match.id,
            title=f"{job.company_name} - {job.title}",
            kind=data.kind,
            content_json=content,
            traceability_json={
                "new_claims": evaluation["issues"],
                "guard_items": evaluation["items"],
                "quality_issues": evaluation["quality_issues"],
                "provider": provider_name,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "semantic_retry_used": generated["semantic_retry_used"],
                "semantic_retry_issues": generated["semantic_retry_issues"],
                "model_validation_issues": generated["model_validation_issues"],
            },
            guard_status=evaluation["status"],
            unachieved_count=evaluation["unachieved_count"],
        )
        db.add(version)
        reservation = db.get(QuotaReservation, ledger.id)
        if reservation is not None:
            reservation.status = "completed"
        db.commit()
    except BaseException:
        _refund_quota_reservation(db, ledger)
        raise
    result = dump(version)
    result["fallback_used"] = fallback_used
    return result


def owned_version(db, user, version_id):
    row = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id, ResumeVersion.user_id == user.id
        )
    )
    if not row:
        raise AppError("RESUME_VERSION_NOT_FOUND", "定制简历不存在。", 404)
    return row


@router.get("/resume-versions")
async def versions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return listed(
        [
            dump(x)
            for x in db.scalars(
                select(ResumeVersion)
                .where(ResumeVersion.user_id == user.id)
                .order_by(ResumeVersion.created_at.desc())
            ).all()
        ]
    )


@router.get("/resume-versions/{version_id}")
async def version_detail(
    version_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return dump(owned_version(db, user, version_id))


@router.patch("/resume-versions/{version_id}")
async def update_version(
    version_id: str,
    data: ResumeContentOutput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = owned_version(db, user, version_id)
    if row.review_status == "approved":
        raise AppError(
            "RESUME_ALREADY_APPROVED",
            "已批准的简历不能直接修改，请重新生成一个定制版本。",
            409,
        )
    confirmed_facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == row.base_resume_id,
                ResumeFact.user_id == user.id,
                ResumeFact.verification_status == "user_confirmed",
            )
        )
    )
    targets = (
        list(
            db.scalars(
                select(CapabilityTarget).where(
                    CapabilityTarget.user_id == user.id,
                    CapabilityTarget.job_id == row.job_id,
                    CapabilityTarget.match_id == row.match_id,
                    CapabilityTarget.status != "achieved",
                )
            )
        )
        if row.kind == "target" and row.match_id
        else []
    )
    base_resume = db.scalar(
        select(Resume).where(
            Resume.id == row.base_resume_id,
            Resume.user_id == user.id,
            Resume.deleted_at.is_(None),
        )
    )
    job = visible_job(db, user, row.job_id)
    if not base_resume or not job:
        raise AppError("RESUME_CONTEXT_MISSING", "定制简历关联的原始简历或岗位不存在。", 409)
    content = data.model_dump()
    if content.get("content_version", 1) == 2:
        estimated_lines = estimate_resume_lines(content)
        if estimated_lines > MAX_RESUME_LINES:
            raise AppError(
                "RESUME_PAGE_BUDGET_EXCEEDED",
                "简历内容超过单页预算，请精简后再保存。",
                422,
                {
                    "estimated_lines": estimated_lines,
                    "max_lines": MAX_RESUME_LINES,
                },
            )
    evaluation = evaluate_resume_content(
        content,
        confirmed_facts,
        targets,
        kind=row.kind,
        expected_headline=job.title,
        expected_contact=base_resume.contact_json,
    )
    traceability = dict(row.traceability_json or {})
    traceability.update(
        {
            "new_claims": evaluation["issues"],
            "guard_items": evaluation["items"],
            "quality_issues": evaluation["quality_issues"],
            "last_edit_source": "user",
        }
    )
    old_export_file_key = row.export_file_key
    row.export_file_key = ""
    row.content_json = content
    row.traceability_json = traceability
    row.guard_status = evaluation["status"]
    row.unachieved_count = evaluation["unachieved_count"]
    row.review_status = "draft"
    row.reviewed_by = None
    row.reviewed_at = None
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="resume_version.edited",
            entity_type="resume_version",
            entity_id=row.id,
            metadata_json={"guard_status": evaluation["status"]},
        )
    )
    if old_export_file_key:
        enqueue_file_deletions(db, [old_export_file_key])
    db.commit()
    if old_export_file_key:
        try:
            LocalStorage().delete(old_export_file_key)
        except Exception as exc:  # best-effort orphan cleanup after the DB commit
            logger.warning(
                "Failed to remove stale resume export after edit: %s",
                type(exc).__name__,
            )
        else:
            # The physical deletion succeeded; remove its durable retry locator.
            task = db.scalar(
                select(StorageDeletionTask).where(
                    StorageDeletionTask.file_key == old_export_file_key
                )
            )
            if task is not None:
                db.delete(task)
                db.commit()
    return dump(row)


@router.post("/resume-versions/{version_id}/submit-review")
async def submit_review(
    version_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_version(db, user, version_id)
    if row.guard_status != "passed":
        raise AppError(
            "FACT_GUARD_BLOCKED",
            "检测到未经确认的新事实，不能提交审核。",
            409,
            row.traceability_json,
        )
    if row.review_status == "approved":
        return dump(row)
    row.review_status = "advisor_review"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="resume_version.submitted",
            entity_type="resume_version",
            entity_id=row.id,
        )
    )
    db.commit()
    return dump(row)


def viewable_version(db, user, version_id):
    """Owner may preview/download once Fact Guard passed; advisor approval is for queue/interview."""
    row = owned_version(db, user, version_id)
    if row.guard_status != "passed":
        raise AppError("FACT_GUARD_BLOCKED", "事实检查未通过，不能预览或下载。", 409)
    return row


def exportable_version(db, user, version_id):
    row = owned_version(db, user, version_id)
    if row.guard_status != "passed" or row.review_status != "approved":
        raise AppError("RESUME_NOT_APPROVED", "仅可导出事实检查通过且已审核的简历。", 409)
    return row


def html_security_headers(disposition: str) -> dict[str, str]:
    return {
        "Content-Disposition": disposition,
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; img-src data:"
        ),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }


def audit_export(db: Session, user: User, row: ResumeVersion, format: str) -> None:
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="resume_version.exported",
            entity_type="resume_version",
            entity_id=row.id,
            metadata_json={"format": format},
        )
    )
    db.commit()


def _discard_unreferenced_export(
    db: Session, storage: LocalStorage, file_key: str
) -> None:
    try:
        storage.delete(file_key)
    except Exception as exc:
        logger.warning("Failed to remove unreferenced resume export: %s", type(exc).__name__)
        try:
            enqueue_file_deletions(db, [file_key])
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to enqueue unreferenced resume export deletion")


def _render_and_cache_docx(db: Session, row: ResumeVersion, storage: LocalStorage) -> bytes:
    content = render_resume_docx(row.content_json, row.title)
    expected_key = row.export_file_key
    try:
        new_key = storage.save(content, ".docx")
    except OSError as exc:
        raise AppError(
            "EXPORT_STORAGE_UNAVAILABLE",
            "导出文件暂时无法保存，请稍后重试。",
            503,
        ) from exc
    row_id = row.id
    user_id = row.user_id
    try:
        # Saving followed earlier validation SELECTs. End that read transaction
        # before the conditional UPDATE so simultaneous cache misses do not
        # trigger SQLite's read-to-write upgrade failure.
        db.commit()
        changed = db.execute(
            update(ResumeVersion)
            .where(
                ResumeVersion.id == row_id,
                ResumeVersion.user_id == user_id,
                ResumeVersion.export_file_key == expected_key,
            )
            .values(export_file_key=new_key)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            # Another request won the cache-key compare-and-set. Its key
            # remains canonical; this request can return equivalent bytes.
            db.rollback()
            _discard_unreferenced_export(db, storage, new_key)
            db.refresh(row)
            return content
        db.commit()
    except Exception:
        db.rollback()
        _discard_unreferenced_export(db, storage, new_key)
        raise
    db.refresh(row)
    return content


@router.get("/resume-versions/{version_id}/preview", response_class=HTMLResponse)
async def preview_version(
    version_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = viewable_version(db, user, version_id)
    audit_export(db, user, row, "html_preview")
    return HTMLResponse(
        render_resume_html(row.content_json, row.title), headers=html_security_headers("inline")
    )


@router.get("/resume-versions/{version_id}/download")
async def download_version(
    version_id: str,
    format: Literal["docx", "html"] = Query(default="docx"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = viewable_version(db, user, version_id)
    if format == "html":
        audit_export(db, user, row, "html_download")
        return HTMLResponse(
            render_resume_html(row.content_json, row.title),
            headers=html_security_headers('attachment; filename="tailored-resume.html"'),
        )
    try:
        storage = LocalStorage()
    except OSError as exc:
        raise AppError(
            "EXPORT_STORAGE_UNAVAILABLE",
            "导出文件暂时不可用，请稍后重试。",
            503,
        ) from exc
    if row.export_file_key:
        try:
            content = storage.path(row.export_file_key).read_bytes()
        except FileNotFoundError:
            # A stale DB key must never turn a recoverable cache miss into a 500.
            content = _render_and_cache_docx(db, row, storage)
        except OSError as exc:
            raise AppError(
                "EXPORT_STORAGE_UNAVAILABLE",
                "导出文件暂时不可用，请稍后重试。",
                503,
            ) from exc
    else:
        content = _render_and_cache_docx(db, row, storage)
    audit_export(db, user, row, "docx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="tailored-resume.docx"'},
    )


class ApplicationIn(BaseModel):
    job_id: str
    resume_version_id: str | None = None
    channel_id: str | None = None
    notes: str = ""


@router.post("/applications", status_code=201)
async def create_application(
    data: ApplicationIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    job = visible_job(db, user, data.job_id)
    if not job:
        raise AppError("JOB_NOT_FOUND", "岗位不存在。", 404)
    version = owned_version(db, user, data.resume_version_id) if data.resume_version_id else None
    if version and version.job_id != job.id:
        raise AppError("RESUME_VERSION_JOB_MISMATCH", "定制简历与所选岗位不一致。", 409)
    if version and (version.guard_status != "passed" or version.review_status != "approved"):
        raise AppError(
            "RESUME_NOT_APPROVED", "定制简历通过事实检查和顾问审核后才能进入投递队列。", 409
        )
    channel = None
    if data.channel_id:
        channel = db.scalar(
            select(ApplicationChannel).where(
                ApplicationChannel.id == data.channel_id,
                or_(
                    ApplicationChannel.owner_user_id.is_(None),
                    ApplicationChannel.owner_user_id == user.id,
                ),
                ApplicationChannel.verify_status != "dead",
            )
        )
        if not channel:
            raise AppError("CHANNEL_NOT_FOUND", "投递渠道不存在或已失效。", 404)
    key = idempotency_key or f"application:{user.id}:{uuid.uuid4()}"
    # All validation is complete; release SQLite's read transaction before the
    # first write in the idempotency/quota claim.
    db.commit()
    app = Application(
        id=str(uuid.uuid4()),
        user_id=user.id,
        job_id=job.id,
        resume_version_id=data.resume_version_id,
        channel_id=data.channel_id,
        source_url=(channel.url if channel and channel.url else job.source_url),
        notes=data.notes,
        status="pending_confirmation",
    )
    ledger = change(
        db,
        user_id=user.id,
        quota_type="application",
        delta=-1,
        reason="加入投递队列",
        idempotency_key=key,
        reference_type="application",
        reference_id=app.id,
        request_hash=request_fingerprint(
            {"operation": "application.create", **data.model_dump(mode="json")}
        ),
    )
    if not was_created(ledger):
        return dump(
            _idempotent_resource(
                db,
                ledger=ledger,
                reference_type="application",
                model=Application,
                user_id=user.id,
            )
        )
    db.add(app)
    db.add(
        ApplicationEvent(
            application_id=app.id,
            from_status=None,
            to_status=app.status,
            actor_user_id=user.id,
            note="创建投递",
        )
    )
    db.commit()
    return dump(app)


def owned_application(db, user, application_id):
    row = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if not row:
        raise AppError("APPLICATION_NOT_FOUND", "投递记录不存在。", 404)
    return row


@router.get("/applications")
async def applications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return listed(
        [
            dump(x)
            for x in db.scalars(
                select(Application)
                .where(Application.user_id == user.id)
                .order_by(Application.created_at.desc())
            ).all()
        ]
    )


@router.get("/applications/{application_id}")
async def application_detail(
    application_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return dump(owned_application(db, user, application_id))


TRANSITIONS = {
    "pending_confirmation": {"withdrawn"},
    "preparing_resume": {"ready_to_apply"},
    "ready_to_apply": {"applied", "withdrawn"},
    "applied": {"contacted", "rejected"},
    "contacted": {"assessment", "interview", "rejected"},
    "assessment": {"interview", "rejected"},
    "interview": {"offer", "rejected"},
}


class StatusIn(BaseModel):
    status: str
    note: str = ""


def _compare_and_set_application_status(
    db: Session,
    *,
    row: Application,
    user_id: str,
    new_status: str,
    note: str,
    confirmed_at: datetime | None = None,
    require_approved_resume: bool = False,
) -> Application:
    row_id = row.id
    old_status = row.status
    # Approval is a continuing gate, not only a queue-entry check. An advisor
    # may revoke approval after the user confirms an application, so every
    # transition into a state that can be submitted must re-check the linked
    # version in the same conditional UPDATE.
    require_approved_resume = require_approved_resume or new_status in {
        "ready_to_apply",
        "applied",
    }
    # The route reaches this helper after validation SELECTs. Release that
    # read transaction before the CAS so concurrent SQLite writers serialize
    # on the UPDATE instead of failing a read-to-write lock upgrade.
    db.commit()
    values: dict = {"status": new_status}
    if new_status == "applied":
        values["applied_at"] = datetime.now(timezone.utc)
    if confirmed_at is not None:
        values["user_confirmed_at"] = confirmed_at
    conditions = [
        Application.id == row_id,
        Application.user_id == user_id,
        Application.status == old_status,
    ]
    if require_approved_resume:
        approved_resume = (
            select(ResumeVersion.id)
            .where(
                ResumeVersion.id == Application.resume_version_id,
                ResumeVersion.user_id == user_id,
                ResumeVersion.job_id == Application.job_id,
                ResumeVersion.guard_status == "passed",
                ResumeVersion.review_status == "approved",
            )
            .exists()
        )
        conditions.append(
            or_(Application.resume_version_id.is_(None), approved_resume)
        )
    changed = db.execute(
        update(Application)
        .where(*conditions)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        if require_approved_resume:
            current = db.scalar(
                select(Application).where(
                    Application.id == row_id,
                    Application.user_id == user_id,
                )
            )
            if current is not None and current.status == old_status and current.resume_version_id:
                approved_version = db.scalar(
                    select(ResumeVersion.id).where(
                        ResumeVersion.id == current.resume_version_id,
                        ResumeVersion.user_id == user_id,
                        ResumeVersion.job_id == current.job_id,
                        ResumeVersion.guard_status == "passed",
                        ResumeVersion.review_status == "approved",
                    )
                )
                if approved_version is None:
                    raise AppError(
                        "RESUME_NOT_APPROVED",
                        "关联简历当前未通过事实检查或审核，不能进入待投递或已投递状态。",
                        409,
                    )
        raise AppError(
            "APPLICATION_STATUS_CONFLICT",
            "投递状态已被其他请求更新，请刷新后重试。",
            409,
        )
    db.add(
        ApplicationEvent(
            application_id=row_id,
            from_status=old_status,
            to_status=new_status,
            actor_user_id=user_id,
            note=note,
        )
    )
    db.commit()
    db.refresh(row)
    return row


@router.patch("/applications/{application_id}/status")
async def update_application(
    application_id: str,
    data: StatusIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = owned_application(db, user, application_id)
    if row.status == "pending_confirmation" and data.status == "preparing_resume":
        raise AppError(
            "APPLICATION_CONFIRMATION_REQUIRED",
            "请使用确认操作后再开始准备投递。",
            409,
        )
    if data.status not in TRANSITIONS.get(row.status, set()):
        raise AppError(
            "INVALID_STATUS_TRANSITION", f"不能从 {row.status} 变更为 {data.status}。", 409
        )
    return dump(
        _compare_and_set_application_status(
            db,
            row=row,
            user_id=user.id,
            new_status=data.status,
            note=data.note,
        )
    )


@router.post("/applications/{application_id}/confirm")
async def confirm_application(
    application_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_application(db, user, application_id)
    if row.status != "pending_confirmation":
        raise AppError("INVALID_STATUS_TRANSITION", "该投递当前不能确认。", 409)
    if row.resume_version_id:
        version = db.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == row.resume_version_id,
                ResumeVersion.user_id == user.id,
                ResumeVersion.job_id == row.job_id,
            )
        )
        if not version or version.guard_status != "passed" or version.review_status != "approved":
            raise AppError(
                "RESUME_NOT_APPROVED",
                "关联简历当前未通过事实检查或审核，不能确认投递。",
                409,
            )
    db.commit()
    return dump(
        _compare_and_set_application_status(
            db,
            row=row,
            user_id=user.id,
            new_status="preparing_resume",
            note="用户确认",
            confirmed_at=datetime.now(timezone.utc),
            require_approved_resume=True,
        )
    )


@router.get("/applications/{application_id}/events")
async def application_events(
    application_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_application(db, user, application_id)
    return listed(
        [
            dump(x)
            for x in db.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == row.id)
                .order_by(ApplicationEvent.created_at)
            ).all()
        ]
    )


class InterviewIn(BaseModel):
    job_id: str
    resume_version_id: str | None = None


@router.post("/interviews", status_code=201)
async def create_interview(
    data: InterviewIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    job = visible_job(db, user, data.job_id)
    if not job:
        raise AppError("JOB_NOT_FOUND", "岗位不存在。", 404)
    version = owned_version(db, user, data.resume_version_id) if data.resume_version_id else None
    if version and version.job_id != job.id:
        raise AppError("RESUME_VERSION_JOB_MISMATCH", "定制简历与所选岗位不一致。", 409)
    if version and (version.guard_status != "passed" or version.review_status != "approved"):
        raise AppError("RESUME_NOT_APPROVED", "仅可使用事实检查通过且已审核的简历生成面试题。", 409)
    base_resume = None
    if version:
        base_resume = db.get(Resume, version.base_resume_id)
    else:
        base_resume = db.scalar(
            select(Resume)
            .where(
                Resume.user_id == user.id,
                Resume.deleted_at.is_(None),
                Resume.facts_confirmed_at.is_not(None),
            )
            .order_by(Resume.created_at.desc())
        )
    confirmed_facts = (
        list(
            db.scalars(
                select(ResumeFact).where(
                    ResumeFact.resume_id == base_resume.id,
                    ResumeFact.user_id == user.id,
                    ResumeFact.verification_status == "user_confirmed",
                )
            )
        )
        if base_resume
        else []
    )
    interview_targets = (
        list(
            db.scalars(
                select(CapabilityTarget).where(
                    CapabilityTarget.user_id == user.id,
                    CapabilityTarget.job_id == job.id,
                    CapabilityTarget.match_id == version.match_id,
                )
            )
        )
        if version and version.match_id
        else []
    )
    expected_unachieved_count = version.unachieved_count if version else 0
    key = idempotency_key or f"interview:{user.id}:{uuid.uuid4()}"
    db.commit()
    ledger = change(
        db,
        user_id=user.id,
        quota_type="interview",
        delta=-1,
        reason="创建模拟面试",
        idempotency_key=key,
        reference_type="interview",
        reference_id=str(uuid.uuid4()),
        request_hash=request_fingerprint(
            {"operation": "interview.create", **data.model_dump(mode="json")}
        ),
    )
    if not was_created(ledger):
        return dump(
            _idempotent_resource(
                db,
                ledger=ledger,
                reference_type="interview",
                model=Interview,
                user_id=user.id,
            )
        )
    db.add(
        QuotaReservation(
            ledger_id=ledger.id,
            user_id=user.id,
            quota_type=ledger.quota_type,
            amount=-ledger.delta,
            resource_type="interview",
            resource_id=ledger.reference_id,
        )
    )
    db.commit()
    try:
        questions = await generate_guarded_interview(
            job,
            version.content_json if version else None,
            confirmed_facts,
            interview_targets,
            expected_unachieved_count=expected_unachieved_count,
        )
        row = Interview(
            id=ledger.reference_id,
            user_id=user.id,
            job_id=job.id,
            resume_version_id=data.resume_version_id,
            question_set_json=questions,
        )
        db.add(row)
        reservation = db.get(QuotaReservation, ledger.id)
        if reservation is not None:
            reservation.status = "completed"
        db.commit()
    except BaseException:
        _refund_quota_reservation(db, ledger)
        raise
    return dump(row)


@router.get("/interviews")
async def interviews(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return listed(
        [
            dump(x)
            for x in db.scalars(
                select(Interview)
                .where(Interview.user_id == user.id)
                .order_by(Interview.created_at.desc())
            ).all()
        ]
    )


@router.get("/interviews/{interview_id}")
async def interview_detail(
    interview_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.scalar(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == user.id)
    )
    if not row:
        raise AppError("INTERVIEW_NOT_FOUND", "模拟面试不存在。", 404)
    return dump(row)


class AnswersIn(BaseModel):
    answers: dict[str, StrictStr] = Field(default_factory=dict, max_length=MAX_INTERVIEW_ANSWERS)

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, value: dict[str, str]) -> dict[str, str]:
        for question_id, answer in value.items():
            if not question_id.strip() or len(question_id) > 100:
                raise ValueError("问题编号不能为空且不能超过 100 个字符")
            if len(answer) > MAX_INTERVIEW_ANSWER_CHARS:
                raise ValueError(
                    f"每条回答不能超过 {MAX_INTERVIEW_ANSWER_CHARS} 个字符"
                )
        return value


def _interview_question_ids(row: Interview) -> set[str]:
    question_set = row.question_set_json if isinstance(row.question_set_json, dict) else {}
    questions = question_set.get("questions", [])
    return {
        question["id"].strip()
        for question in questions
        if isinstance(question, dict)
        and isinstance(question.get("id"), str)
        and question["id"].strip()
    }


@router.patch("/interviews/{interview_id}/answers")
async def answers(
    interview_id: str,
    data: AnswersIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == user.id)
    )
    if not row:
        raise AppError("INTERVIEW_NOT_FOUND", "模拟面试不存在。", 404)
    if row.status != "draft":
        raise AppError("INTERVIEW_NOT_EDITABLE", "已提交的模拟面试不能继续修改回答。", 409)
    unknown_ids = sorted(set(data.answers) - _interview_question_ids(row))
    if unknown_ids:
        raise AppError(
            "INTERVIEW_QUESTION_NOT_FOUND",
            "回答中包含不属于本次模拟面试的问题。",
            422,
            {"question_ids": unknown_ids[:10]},
        )
    row.answers_json = data.answers
    db.commit()
    return dump(row)


@router.post("/interviews/{interview_id}/submit")
async def submit_interview(
    interview_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.scalar(
        select(Interview).where(Interview.id == interview_id, Interview.user_id == user.id)
    )
    if not row:
        raise AppError("INTERVIEW_NOT_FOUND", "模拟面试不存在。", 404)
    if row.status != "draft":
        raise AppError("INVALID_INTERVIEW_STATUS", "该模拟面试当前不能提交。", 409)
    allowed_ids = _interview_question_ids(row)
    stored_answers = row.answers_json if isinstance(row.answers_json, dict) else {}
    invalid_stored_answers = (
        len(stored_answers) > MAX_INTERVIEW_ANSWERS
        or any(
            question_id not in allowed_ids
            or not isinstance(answer, str)
            or len(answer) > MAX_INTERVIEW_ANSWER_CHARS
            for question_id, answer in stored_answers.items()
        )
    )
    if invalid_stored_answers:
        raise AppError(
            "INTERVIEW_ANSWERS_INVALID",
            "已保存的回答与当前题组不一致，请重新保存后再提交。",
            409,
        )
    valid_answers = {
        question_id: answer
        for question_id, answer in stored_answers.items()
        if question_id in allowed_ids
        and isinstance(answer, str)
        and answer.strip()
        and len(answer) <= MAX_INTERVIEW_ANSWER_CHARS
    }
    if not valid_answers:
        raise AppError("INTERVIEW_ANSWERS_REQUIRED", "请至少填写一条回答后再提交。", 409)
    row.status = "submitted"
    db.commit()
    return dump(row)


@router.get("/packages")
async def packages(db: Session = Depends(get_db)):
    return listed(
        [dump(x) for x in db.scalars(select(Package).where(Package.is_active.is_(True))).all()]
    )


@router.get("/quotas")
async def quotas(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {q: balance(db, user.id, q) for q in ["match", "resume", "application", "interview"]}


@router.get("/quotas/ledger")
async def quota_ledger(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return listed(
        [
            dump(x)
            for x in db.scalars(
                select(QuotaLedger)
                .where(QuotaLedger.user_id == user.id)
                .order_by(QuotaLedger.created_at.desc())
            ).all()
        ]
    )


@router.get("/reports/weekly")
async def report(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return weekly_report(db, user.id)


@router.get("/notifications")
async def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
    ).all()
    return {
        **listed([dump(row) for row in rows]),
        "unread_count": sum(row.read_at is None for row in rows),
    }


@router.post("/notifications/{notification_id}/read")
async def read_notification(
    notification_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if not row:
        raise AppError("NOTIFICATION_NOT_FOUND", "通知不存在。", 404)
    row.read_at = datetime.now(timezone.utc)
    db.commit()
    return dump(row)


@router.get("/account/export")
async def account_export(user: User = Depends(current_user), db: Session = Depends(get_db)):
    applications = list(db.scalars(select(Application).where(Application.user_id == user.id)))
    application_ids = [application.id for application in applications]
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": dump(user, {"password_hash"}),
        "profile": dump(db.get(UserProfile, user.id)) if db.get(UserProfile, user.id) else None,
        "resumes": [
            dump(row, {"original_file_key"})
            for row in db.scalars(select(Resume).where(Resume.user_id == user.id))
        ],
        "resume_facts": [
            dump(row) for row in db.scalars(select(ResumeFact).where(ResumeFact.user_id == user.id))
        ],
        "capability_targets": [
            dump(row)
            for row in db.scalars(
                select(CapabilityTarget).where(CapabilityTarget.user_id == user.id)
            )
        ],
        "jobs": [
            dump(row)
            for row in db.scalars(select(Job).where(owned_job_clause(user.id)))
        ],
        "matches": [dump(row) for row in db.scalars(select(Match).where(Match.user_id == user.id))],
        "resume_versions": [
            dump(row, {"export_file_key"})
            for row in db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user.id))
        ],
        "applications": [dump(row) for row in applications],
        "application_events": [
            dump(row)
            for row in db.scalars(
                select(ApplicationEvent).where(ApplicationEvent.application_id.in_(application_ids))
            )
        ]
        if application_ids
        else [],
        "interviews": [
            dump(row) for row in db.scalars(select(Interview).where(Interview.user_id == user.id))
        ],
        "orders": [dump(row) for row in db.scalars(select(Order).where(Order.user_id == user.id))],
        "quota_ledger": [
            dump(row)
            for row in db.scalars(select(QuotaLedger).where(QuotaLedger.user_id == user.id))
        ],
        "notifications": [
            dump(row)
            for row in db.scalars(select(Notification).where(Notification.user_id == user.id))
        ],
        "audit_logs": [
            dump(row, {"ip_hash"})
            for row in db.scalars(select(AuditLog).where(AuditLog.actor_user_id == user.id))
        ],
    }
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": 'attachment; filename="ai-job-coach-data.json"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
