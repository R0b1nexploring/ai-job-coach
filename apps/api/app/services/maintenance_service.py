from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import (
    AuditLog,
    Interview,
    Job,
    QuotaLedger,
    QuotaReservation,
    ResumeBundle,
    ResumeBundleRun,
    ResumeVersion,
    User,
)
from app.providers.storage.local import LocalStorage
from app.services.privacy_service import purge_user_data
from app.services.quota_service import change, request_fingerprint, was_created
from app.services.storage_cleanup import process_storage_deletions

# A normal provider request is bounded, but one business generation can include
# validation and a semantic retry. Keep the crash-recovery window comfortably
# above that total so maintenance never refunds a request that is still working.
QUOTA_RESERVATION_TIMEOUT = timedelta(hours=1)
TASK_LEASE_TIMEOUT = timedelta(seconds=90)


def requeue_stale_bundle_runs(db: Session, *, current: datetime) -> int:
    cutoff = current - TASK_LEASE_TIMEOUT
    runs = list(
        db.scalars(
            select(ResumeBundleRun).where(
                ResumeBundleRun.status == "generating",
                or_(
                    ResumeBundleRun.lease_expires_at <= current,
                    ResumeBundleRun.updated_at <= cutoff,
                ),
            )
        )
    )
    requeued = 0
    for run in runs:
        bundle = db.get(ResumeBundle, run.bundle_id)
        if (run.attempts or 0) >= (run.max_attempts or 3):
            run.status = "failed"
            run.phase = "failed"
            run.public_error_code = "TASK_TIMEOUT"
            run.last_error = "worker lease expired"
            if bundle is not None:
                bundle.status = "failed"
                bundle.generation_metadata_json = {
                    **(bundle.generation_metadata_json or {}),
                    "error": "task_timeout",
                    "error_message": "生成任务多次中断，请稍后重试。",
                }
                _refund_bundle_reservation(db, bundle.id)
            continue
        run.status = "queued"
        run.phase = "queued"
        run.lease_expires_at = None
        run.heartbeat_at = None
        run.last_error = ""
        run.public_error_code = ""
        if bundle is not None:
            bundle.status = "queued"
        requeued += 1
    if runs:
        db.commit()
    return requeued


def _refund_bundle_reservation(db: Session, bundle_id: str) -> None:
    reservation = db.scalar(
        select(QuotaReservation)
        .where(
            QuotaReservation.resource_type == "resume_bundle",
            QuotaReservation.resource_id == bundle_id,
            QuotaReservation.status == "pending",
        )
        .order_by(QuotaReservation.created_at.desc())
    )
    if reservation is None:
        return
    ledger = db.get(QuotaLedger, reservation.ledger_id)
    if ledger is None or ledger.delta >= 0:
        reservation.status = "refunded"
        return
    refund = change(
        db,
        user_id=reservation.user_id,
        quota_type=reservation.quota_type,
        delta=reservation.amount,
        reason="生成任务中断退回",
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


def reconcile_stale_quota_reservations(
    db: Session,
    *,
    current: datetime,
) -> int:
    """Refund generation debits left pending after a crashed worker."""
    cutoff = current - QUOTA_RESERVATION_TIMEOUT
    reservations = list(
        db.scalars(
            select(QuotaReservation).where(
                QuotaReservation.status == "pending",
                QuotaReservation.created_at <= cutoff,
            )
        )
    )
    refunded = 0
    for reservation in reservations:
        model = {
            "resume_version": ResumeVersion,
            "interview": Interview,
        }.get(reservation.resource_type)
        if model is None:
            continue
        if db.get(model, reservation.resource_id) is not None:
            reservation.status = "completed"
            continue
        ledger = db.get(QuotaLedger, reservation.ledger_id)
        if ledger is None or ledger.delta >= 0:
            reservation.status = "refunded"
            continue
        refund = change(
            db,
            user_id=reservation.user_id,
            quota_type=reservation.quota_type,
            delta=reservation.amount,
            reason="生成任务超时自动退回",
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
        if refund.reference_id == reservation.ledger_id:
            reservation.status = "refunded"
            if was_created(refund):
                refunded += 1
    db.commit()
    return refunded


def _claim_user_for_purge(
    db: Session,
    *,
    user_id: str,
    reason: str,
    current: datetime,
    deletion_cutoff: datetime,
) -> tuple[User, str] | None:
    """Re-check eligibility and atomically prevent activity/retention races."""
    if reason == "retention_expired":
        previous_status = "active"
        eligible = and_(
            User.role == "user",
            User.status == previous_status,
            User.retention_expires_at.is_not(None),
            User.retention_expires_at <= current,
        )
    else:
        previous_status = "deletion_requested"
        eligible = and_(
            User.role == "user",
            User.status == previous_status,
            or_(
                User.deletion_requested_at <= deletion_cutoff,
                and_(
                    User.deletion_requested_at.is_(None),
                    User.updated_at <= deletion_cutoff,
                ),
            ),
        )

    transition = db.execute(
        update(User)
        .where(User.id == user_id, eligible)
        .values(status="purging")
        .execution_options(synchronize_session=False)
    )
    if transition.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    claimed = db.get(User, user_id, populate_existing=True)
    if claimed is None:
        return None
    return claimed, previous_status


def _restore_failed_claim(db: Session, user_id: str, previous_status: str) -> None:
    db.rollback()
    db.execute(
        update(User)
        .where(User.id == user_id, User.status == "purging")
        .values(status=previous_status)
        .execution_options(synchronize_session=False)
    )
    db.commit()


def maintenance_candidates(db: Session, now: datetime | None = None) -> dict:
    settings = get_settings()
    current = now or datetime.now(timezone.utc)
    deletion_cutoff = current - timedelta(days=settings.deletion_grace_days)
    job_cutoff = current - timedelta(days=settings.job_stale_days)
    expired_users = list(
        db.scalars(
            select(User).where(
                User.role == "user",
                User.status == "active",
                User.retention_expires_at.is_not(None),
                User.retention_expires_at <= current,
            )
        )
    )
    deletion_requests = list(
        db.scalars(
            select(User).where(
                User.role == "user",
                User.status == "deletion_requested",
                or_(
                    User.deletion_requested_at <= deletion_cutoff,
                    and_(
                        User.deletion_requested_at.is_(None),
                        User.updated_at <= deletion_cutoff,
                    ),
                ),
            )
        )
    )
    stale_jobs = list(
        db.scalars(
            select(Job).where(
                Job.status == "active",
                Job.published_at.is_not(None),
                Job.published_at <= job_cutoff,
            )
        )
    )
    return {
        "expired_users": expired_users,
        "deletion_requests": deletion_requests,
        "stale_jobs": stale_jobs,
        "retention_days": settings.data_retention_days,
        "deletion_grace_days": settings.deletion_grace_days,
        "job_stale_days": settings.job_stale_days,
    }


def run_maintenance(
    db: Session,
    *,
    execute: bool = False,
    now: datetime | None = None,
    storage: LocalStorage | None = None,
) -> dict:
    current = now or datetime.now(timezone.utc)
    candidates = maintenance_candidates(db, current)
    users = {user.id: (user, "retention_expired") for user in candidates["expired_users"]}
    users.update(
        {user.id: (user, "deletion_grace_elapsed") for user in candidates["deletion_requests"]}
    )
    result = {
        "mode": "execute" if execute else "dry_run",
        "expired_user_count": len(candidates["expired_users"]),
        "deletion_request_count": len(candidates["deletion_requests"]),
        "stale_job_count": len(candidates["stale_jobs"]),
        "purged_user_count": 0,
        "purge_failed_count": 0,
        "expired_job_count": 0,
        "quota_reservation_refund_count": 0,
        "requeued_bundle_count": 0,
    }
    if not execute:
        return result
    file_storage = storage or LocalStorage()
    try:
        process_storage_deletions(db, file_storage)
    except Exception:
        # Account and job maintenance remain useful even when the cleanup queue's
        # database is temporarily unavailable. The durable rows remain retryable.
        db.rollback()
    result["quota_reservation_refund_count"] = reconcile_stale_quota_reservations(
        db,
        current=current,
    )
    result["requeued_bundle_count"] = requeue_stale_bundle_runs(db, current=current)
    deletion_cutoff = current - timedelta(days=get_settings().deletion_grace_days)
    for user, reason in users.values():
        user_id = user.id
        claimed = _claim_user_for_purge(
            db,
            user_id=user_id,
            reason=reason,
            current=current,
            deletion_cutoff=deletion_cutoff,
        )
        if claimed is None:
            continue
        claimed_user, previous_status = claimed
        try:
            purge_user_data(
                db,
                claimed_user,
                file_storage,
                audit_action="account.retention_purged",
                audit_metadata={"reason": reason},
            )
        except Exception:
            # One malformed account must not prevent unrelated users or stale jobs
            # from completing their maintenance cycle.
            _restore_failed_claim(db, user_id, previous_status)
            result["purge_failed_count"] += 1
            continue
        result["purged_user_count"] += 1
    for job in candidates["stale_jobs"]:
        transition = db.execute(
            update(Job)
            .where(
                Job.id == job.id,
                Job.status == "active",
                Job.published_at.is_not(None),
                Job.published_at <= current - timedelta(days=get_settings().job_stale_days),
            )
            .values(status="expired")
            .execution_options(synchronize_session=False)
        )
        if transition.rowcount != 1:
            continue
        db.add(
            AuditLog(
                actor_user_id=None,
                action="job.expired_by_maintenance",
                entity_type="job",
                entity_id=job.id,
                metadata_json={"published_at": job.published_at.isoformat()},
            )
        )
        result["expired_job_count"] += 1
    db.commit()
    return result
