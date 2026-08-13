import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.models.entities import (
    AuditLog,
    Job,
    QuotaLedger,
    QuotaReservation,
    StorageDeletionTask,
    User,
    UserProfile,
)
from app.security import hash_password
from app.services import maintenance_service
from app.services.maintenance_service import run_maintenance


def add_user(db, email: str, *, status="active", retention_expires_at=None, requested_at=None):
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password("Password123!"),
        display_name="维护测试用户",
        status=status,
        retention_expires_at=retention_expires_at,
        deletion_requested_at=requested_at,
    )
    db.add(user)
    # Seed the account and its profile in the same flush. Production never adds
    # new PII to an already inactive account, which the runtime guard correctly
    # rejects.
    db.add(UserProfile(user_id=user.id))
    db.flush()
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
        "purge_failed_count": 0,
        "expired_job_count": 0,
        "quota_reservation_refund_count": 0,
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


def test_maintenance_isolates_one_user_purge_failure(db, monkeypatch):
    now = datetime.now(timezone.utc)
    failing = add_user(
        db,
        "failing@example.test",
        retention_expires_at=now - timedelta(days=1),
    )
    healthy = add_user(
        db,
        "healthy@example.test",
        retention_expires_at=now - timedelta(days=1),
    )
    db.commit()
    original_purge = maintenance_service.purge_user_data

    def flaky_purge(session, user, storage, **kwargs):
        if user.id == failing.id:
            user.display_name = "不得提交的部分修改"
            session.flush()
            raise RuntimeError("simulated database purge failure")
        return original_purge(session, user, storage, **kwargs)

    monkeypatch.setattr(maintenance_service, "purge_user_data", flaky_purge)
    result = maintenance_service.run_maintenance(db, execute=True, now=now)

    db.expire_all()
    assert result["purge_failed_count"] == 1
    assert result["purged_user_count"] == 1
    assert db.get(User, failing.id).status == "active"
    assert db.get(User, failing.id).display_name == "维护测试用户"
    assert db.get(User, healthy.id).status == "deleted"


def test_maintenance_rechecks_retention_after_stale_candidate_query(db, monkeypatch):
    now = datetime.now(timezone.utc)
    renewed = add_user(
        db,
        "renewed-before-purge@example.test",
        retention_expires_at=now - timedelta(days=1),
    )
    db.commit()

    original_candidates = maintenance_service.maintenance_candidates

    def stale_candidates(session, current=None):
        snapshot = original_candidates(session, current)
        session.execute(
            update(User)
            .where(User.id == renewed.id)
            .values(
                retention_expires_at=now + timedelta(days=30),
                last_active_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        session.commit()
        return snapshot

    monkeypatch.setattr(maintenance_service, "maintenance_candidates", stale_candidates)
    result = run_maintenance(db, execute=True, now=now)

    db.expire_all()
    stored = db.get(User, renewed.id)
    assert result["purged_user_count"] == 0
    assert stored.status == "active"
    assert stored.retention_expires_at.replace(tzinfo=timezone.utc) > now


def test_maintenance_retries_durable_storage_deletion_tasks(db):
    task = StorageDeletionTask(
        file_key="retry-private-file.docx",
        attempts=1,
        last_error="OSError",
    )
    db.add(task)
    db.commit()
    deleted: list[str] = []

    class RecordingStorage:
        def delete(self, key: str) -> None:
            deleted.append(key)

    result = run_maintenance(db, execute=True, storage=RecordingStorage())

    assert result["purge_failed_count"] == 0
    assert deleted == ["retry-private-file.docx"]
    assert db.get(StorageDeletionTask, task.id) is None


def test_maintenance_refunds_stale_crashed_generation_reservation(db):
    current = datetime.now(timezone.utc)
    user = add_user(db, "crashed-generation@example.test")
    db.flush()
    balance_row = maintenance_service.change(
        db,
        user_id=user.id,
        quota_type="interview",
        delta=1,
        reason="测试额度",
        idempotency_key="crashed-generation-grant",
    )
    assert balance_row.delta == 1
    reservation_ledger = maintenance_service.change(
        db,
        user_id=user.id,
        quota_type="interview",
        delta=-1,
        reason="创建模拟面试",
        idempotency_key="crashed-generation-debit",
        reference_type="interview",
        reference_id="missing-interview",
    )
    db.add(
        QuotaReservation(
            ledger_id=reservation_ledger.id,
            user_id=user.id,
            quota_type="interview",
            amount=1,
            resource_type="interview",
            resource_id="missing-interview",
            created_at=current - timedelta(minutes=61),
            updated_at=current - timedelta(minutes=61),
        )
    )
    db.commit()

    result = run_maintenance(db, execute=True, now=current)

    db.expire_all()
    reservation = db.get(QuotaReservation, reservation_ledger.id)
    assert result["quota_reservation_refund_count"] == 1
    assert reservation.status == "refunded"
    assert db.scalar(
        select(QuotaLedger.delta).where(
            QuotaLedger.idempotency_key == f"quota-refund:{reservation_ledger.id}"
        )
    ) == 1
