from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.entities import AuditLog, Job, User, UserProfile
from app.security import hash_password
from app.services.maintenance_service import run_maintenance


def add_user(db, email: str, *, status="active", retention_expires_at=None, requested_at=None):
    user = User(
        email=email,
        password_hash=hash_password("Password123!"),
        display_name="维护测试用户",
        status=status,
        retention_expires_at=retention_expires_at,
        deletion_requested_at=requested_at,
    )
    db.add(user)
    db.flush()
    db.add(UserProfile(user_id=user.id))
    return user


def test_maintenance_dry_run_then_executes_retention_and_job_expiry(db):
    now = datetime.now(timezone.utc)
    expired = add_user(
        db,
        "expired@example.test",
        retention_expires_at=now - timedelta(days=1),
    )
    requested = add_user(
        db,
        "requested@example.test",
        status="deletion_requested",
        requested_at=now - timedelta(days=8),
    )
    fresh = add_user(
        db,
        "fresh@example.test",
        retention_expires_at=now + timedelta(days=30),
    )
    old_job = Job(
        created_by=fresh.id,
        company_name="过期岗位公司",
        title="旧岗位",
        raw_jd="公开岗位说明",
        content_hash="old-job",
        published_at=now - timedelta(days=60),
    )
    fresh_job = Job(
        created_by=fresh.id,
        company_name="新岗位公司",
        title="新岗位",
        raw_jd="公开岗位说明",
        content_hash="fresh-job",
        published_at=now - timedelta(days=2),
    )
    unknown_date_job = Job(
        created_by=fresh.id,
        company_name="日期待确认公司",
        title="日期待确认岗位",
        raw_jd="公开岗位说明",
        content_hash="unknown-job",
        published_at=None,
    )
    db.add_all([old_job, fresh_job, unknown_date_job])
    db.commit()

    preview = run_maintenance(db, now=now)
    assert preview == {
        "mode": "dry_run",
        "expired_user_count": 1,
        "deletion_request_count": 1,
        "stale_job_count": 1,
        "purged_user_count": 0,
        "expired_job_count": 0,
    }
    assert expired.status == "active" and requested.status == "deletion_requested"
    assert old_job.status == "active"

    result = run_maintenance(db, execute=True, now=now)
    assert result["purged_user_count"] == 2
    assert result["expired_job_count"] == 1
    db.refresh(expired)
    db.refresh(requested)
    db.refresh(fresh)
    db.refresh(old_job)
    db.refresh(fresh_job)
    db.refresh(unknown_date_job)
    assert expired.status == "deleted" and requested.status == "deleted"
    assert fresh.status == "active"
    assert old_job.status == "expired"
    assert fresh_job.status == "active" and unknown_date_job.status == "active"
    actions = set(db.scalars(select(AuditLog.action)))
    assert "account.retention_purged" in actions
    assert "job.expired_by_maintenance" in actions
