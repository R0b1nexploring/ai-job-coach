from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import AuditLog, Job, User
from app.providers.storage.local import LocalStorage
from app.services.privacy_service import purge_user_data


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
    candidates = maintenance_candidates(db, now)
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
        "expired_job_count": 0,
    }
    if not execute:
        return result
    file_storage = storage or LocalStorage()
    for user, reason in users.values():
        summary = purge_user_data(db, user, file_storage)
        db.add(
            AuditLog(
                actor_user_id=None,
                action="account.retention_purged",
                entity_type="user",
                entity_id=user.id,
                metadata_json={"reason": reason, **summary},
            )
        )
        result["purged_user_count"] += 1
    for job in candidates["stale_jobs"]:
        job.status = "expired"
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
