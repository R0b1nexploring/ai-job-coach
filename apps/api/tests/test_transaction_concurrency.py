import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api.routes import workflow
from app.errors import AppError
from app.models.entities import (
    Application,
    ApplicationEvent,
    CapabilityTarget,
    CapabilityTargetRun,
    Interview,
    Job,
    Match,
    QuotaLedger,
    Resume,
    ResumeVersion,
    User,
)
from app.providers.storage.local import LocalStorage
from app.services.quota_service import balance, change, request_fingerprint


def _user(user_id: str = "concurrency-user") -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.test",
        password_hash="test",
    )


def _job(user_id: str, job_id: str = "concurrency-job") -> Job:
    return Job(
        id=job_id,
        created_by=user_id,
        company_name="并发测试公司",
        title="测试工程师",
        raw_jd="负责测试流程",
        content_hash=job_id,
    )


def test_true_concurrent_quota_calls_do_not_overdraw_or_lock(db):
    user = _user("quota-different-keys")
    db.add(user)
    db.flush()
    change(
        db,
        user_id=user.id,
        quota_type="resume",
        delta=1,
        reason="测试额度",
        idempotency_key="different-keys-grant",
    )
    db.commit()

    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def debit(key: str) -> str:
        with Session() as session:
            assert balance(session, user.id, "resume") == 1
            barrier.wait(timeout=5)
            try:
                change(
                    session,
                    user_id=user.id,
                    quota_type="resume",
                    delta=-1,
                    reason="并发使用",
                    idempotency_key=key,
                )
                session.commit()
                return "created"
            except AppError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(debit, ["different-a", "different-b"]))

    assert sorted(results) == ["QUOTA_EXHAUSTED", "created"]
    db.expire_all()
    assert balance(db, user.id, "resume") == 0


def test_true_concurrent_same_quota_key_replays_before_balance_check(db):
    user = _user("quota-same-key")
    db.add(user)
    db.flush()
    change(
        db,
        user_id=user.id,
        quota_type="interview",
        delta=1,
        reason="测试额度",
        idempotency_key="same-key-grant",
    )
    db.commit()

    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def debit() -> str:
        with Session() as session:
            assert balance(session, user.id, "interview") == 1
            barrier.wait(timeout=5)
            row = change(
                session,
                user_id=user.id,
                quota_type="interview",
                delta=-1,
                reason="并发使用",
                idempotency_key="same-debit",
            )
            session.commit()
            return row.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ledger_ids = list(executor.map(lambda _value: debit(), range(2)))

    assert ledger_ids[0] == ledger_ids[1]
    db.expire_all()
    assert balance(db, user.id, "interview") == 0
    assert (
        db.scalar(
            select(func.count(QuotaLedger.id)).where(
                QuotaLedger.user_id == user.id,
                QuotaLedger.quota_type == "interview",
                QuotaLedger.idempotency_key == "same-debit",
            )
        )
        == 1
    )


def test_quota_idempotency_key_is_bound_to_request_fingerprint(db):
    user = _user("quota-payload")
    db.add(user)
    db.flush()
    change(
        db,
        user_id=user.id,
        quota_type="application",
        delta=2,
        reason="测试额度",
        idempotency_key="payload-grant",
    )
    change(
        db,
        user_id=user.id,
        quota_type="application",
        delta=-1,
        reason="创建投递",
        idempotency_key="payload-key",
        request_hash=request_fingerprint({"job_id": "job-a"}),
    )
    with pytest.raises(AppError) as raised:
        change(
            db,
            user_id=user.id,
            quota_type="application",
            delta=-1,
            reason="创建投递",
            idempotency_key="payload-key",
            request_hash=request_fingerprint({"job_id": "job-b"}),
        )
    assert raised.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert balance(db, user.id, "application") == 1


def test_same_interview_request_calls_generator_only_once(db, monkeypatch):
    user = _user("interview-claim")
    job = _job(user.id, "interview-claim-job")
    db.add(user)
    db.flush()
    db.add(job)
    db.flush()
    change(
        db,
        user_id=user.id,
        quota_type="interview",
        delta=1,
        reason="测试额度",
        idempotency_key="interview-claim-grant",
    )
    db.commit()

    generator_entered = Event()
    release_generator = Event()
    calls = 0
    calls_lock = Lock()

    async def fake_generate(*_args, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        generator_entered.set()
        await asyncio.to_thread(release_generator.wait, 5)
        return {"questions": [{"id": "q1", "question": "请介绍项目"}]}

    monkeypatch.setattr(workflow, "generate_guarded_interview", fake_generate)
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    start = Barrier(2)

    def create() -> tuple[str, str]:
        with Session() as session:
            current_user = session.get(User, user.id)
            start.wait(timeout=5)
            try:
                result = asyncio.run(
                    workflow.create_interview(
                        workflow.InterviewIn(job_id=job.id),
                        idempotency_key="one-external-call",
                        user=current_user,
                        db=session,
                    )
                )
                return "created", result["id"]
            except AppError as exc:
                if exc.code == "IDEMPOTENCY_RESULT_UNAVAILABLE":
                    release_generator.set()
                return exc.code, ""

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create) for _ in range(2)]
        assert generator_entered.wait(timeout=5)
        results = [future.result(timeout=10) for future in futures]

    assert calls == 1
    assert sorted(result[0] for result in results) == [
        "IDEMPOTENCY_RESULT_UNAVAILABLE",
        "created",
    ]
    db.expire_all()
    assert balance(db, user.id, "interview") == 0
    assert db.scalar(select(func.count(Interview.id))) == 1


def test_failed_interview_generation_refunds_reserved_quota(db, monkeypatch):
    user = _user("interview-refund")
    job = _job(user.id, "interview-refund-job")
    db.add(user)
    db.flush()
    db.add(job)
    db.flush()
    change(
        db,
        user_id=user.id,
        quota_type="interview",
        delta=1,
        reason="测试额度",
        idempotency_key="interview-refund-grant",
    )
    db.commit()
    calls = 0

    async def fail_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider failed")

    monkeypatch.setattr(workflow, "generate_guarded_interview", fail_generate)
    with pytest.raises(RuntimeError, match="provider failed"):
        asyncio.run(
            workflow.create_interview(
                workflow.InterviewIn(job_id=job.id),
                idempotency_key="refunded-interview",
                user=user,
                db=db,
            )
        )
    assert calls == 1
    db.expire_all()
    assert balance(db, user.id, "interview") == 1
    deltas = list(
        db.scalars(
            select(QuotaLedger.delta)
            .where(
                QuotaLedger.user_id == user.id,
                QuotaLedger.quota_type == "interview",
                QuotaLedger.idempotency_key != "interview-refund-grant",
            )
            .order_by(QuotaLedger.created_at)
        )
    )
    assert deltas == [-1, 1]


def test_zero_interview_quota_blocks_before_external_call(db, monkeypatch):
    user = _user("interview-zero")
    job = _job(user.id, "interview-zero-job")
    db.add(user)
    db.flush()
    db.add(job)
    db.commit()
    calls = 0

    async def fake_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"questions": []}

    monkeypatch.setattr(workflow, "generate_guarded_interview", fake_generate)
    with pytest.raises(AppError) as raised:
        asyncio.run(
            workflow.create_interview(
                workflow.InterviewIn(job_id=job.id),
                idempotency_key="zero-quota-interview",
                user=user,
                db=db,
            )
        )
    assert raised.value.code == "QUOTA_EXHAUSTED"
    assert calls == 0
    assert db.scalar(select(func.count(Interview.id))) == 0


def test_application_status_compare_and_set_rejects_stale_session(db):
    user = _user("application-cas")
    job = _job(user.id, "application-cas-job")
    application = Application(
        id="application-cas-row",
        user_id=user.id,
        job_id=job.id,
        status="ready_to_apply",
    )
    db.add(user)
    db.flush()
    db.add(job)
    db.flush()
    db.add(application)
    db.commit()
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    with Session() as first, Session() as stale:
        first_row = first.get(Application, application.id)
        stale_row = stale.get(Application, application.id)
        workflow._compare_and_set_application_status(
            first,
            row=first_row,
            user_id=user.id,
            new_status="applied",
            note="first",
        )
        with pytest.raises(AppError) as raised:
            workflow._compare_and_set_application_status(
                stale,
                row=stale_row,
                user_id=user.id,
                new_status="withdrawn",
                note="stale",
            )
        assert raised.value.code == "APPLICATION_STATUS_CONFLICT"

    db.expire_all()
    assert db.get(Application, application.id).status == "applied"
    assert db.scalar(select(func.count(ApplicationEvent.id))) == 1


def test_application_confirm_revalidates_linked_resume(db):
    user = _user("confirm-guard")
    job = _job(user.id, "confirm-guard-job")
    resume = Resume(
        id="confirm-guard-resume",
        user_id=user.id,
        original_file_key="unused.docx",
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="简历",
    )
    version = ResumeVersion(
        id="confirm-guard-version",
        user_id=user.id,
        base_resume_id=resume.id,
        job_id=job.id,
        title="测试简历",
        content_json={},
        traceability_json={},
        guard_status="blocked",
        review_status="approved",
    )
    application = Application(
        id="confirm-guard-application",
        user_id=user.id,
        job_id=job.id,
        resume_version_id=version.id,
        status="pending_confirmation",
    )
    db.add(user)
    db.flush()
    db.add_all([job, resume])
    db.flush()
    db.add(version)
    db.flush()
    db.add(application)
    db.commit()

    with pytest.raises(AppError) as raised:
        asyncio.run(
            workflow.confirm_application(application.id, user=user, db=db)
        )
    assert raised.value.code == "RESUME_NOT_APPROVED"
    db.refresh(application)
    assert application.status == "pending_confirmation"
    assert application.user_confirmed_at is None


@pytest.mark.parametrize(
    ("old_status", "new_status"),
    [
        ("preparing_resume", "ready_to_apply"),
        ("ready_to_apply", "applied"),
    ],
)
def test_application_revalidates_linked_resume_before_submittable_states(
    db, old_status, new_status
):
    user = _user(f"continuous-approval-{old_status}")
    job = _job(user.id, f"continuous-approval-job-{old_status}")
    resume = Resume(
        id=f"continuous-approval-resume-{old_status}",
        user_id=user.id,
        original_file_key="unused.docx",
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="简历",
    )
    version = ResumeVersion(
        id=f"continuous-approval-version-{old_status}",
        user_id=user.id,
        base_resume_id=resume.id,
        job_id=job.id,
        title="测试简历",
        content_json={},
        traceability_json={},
        guard_status="passed",
        # Simulate an advisor revoking approval after queue confirmation.
        review_status="rejected",
    )
    application = Application(
        id=f"continuous-approval-application-{old_status}",
        user_id=user.id,
        job_id=job.id,
        resume_version_id=version.id,
        status=old_status,
    )
    db.add(user)
    db.flush()
    db.add_all([job, resume])
    db.flush()
    db.add(version)
    db.flush()
    db.add(application)
    db.commit()

    with pytest.raises(AppError) as raised:
        asyncio.run(
            workflow.update_application(
                application.id,
                workflow.StatusIn(status=new_status),
                user=user,
                db=db,
            )
        )

    assert raised.value.code == "RESUME_NOT_APPROVED"
    db.expire_all()
    assert db.get(Application, application.id).status == old_status
    assert db.scalar(select(func.count(ApplicationEvent.id))) == 0


def test_docx_cache_compare_and_set_removes_losing_file(db):
    user = _user("docx-cas")
    job = _job(user.id, "docx-cas-job")
    resume = Resume(
        id="docx-cas-resume",
        user_id=user.id,
        original_file_key="unused.docx",
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="简历",
    )
    version = ResumeVersion(
        id="docx-cas-version",
        user_id=user.id,
        base_resume_id=resume.id,
        job_id=job.id,
        title="测试简历",
        content_json={"headline": "测试工程师", "contact": {}, "sections": []},
        traceability_json={},
        guard_status="passed",
        review_status="approved",
    )
    db.add(user)
    db.flush()
    db.add_all([job, resume])
    db.flush()
    db.add(version)
    db.commit()
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    saved = Barrier(2)

    class ConcurrentStorage(LocalStorage):
        def save(self, content: bytes, suffix: str) -> str:
            key = super().save(content, suffix)
            saved.wait(timeout=5)
            return key

    storage = ConcurrentStorage()

    def render() -> str:
        with Session() as session:
            row = session.get(ResumeVersion, version.id)
            workflow._render_and_cache_docx(session, row, storage)
            return row.export_file_key

    with ThreadPoolExecutor(max_workers=2) as executor:
        observed_keys = list(executor.map(lambda _value: render(), range(2)))

    db.expire_all()
    winning_key = db.get(ResumeVersion, version.id).export_file_key
    assert observed_keys == [winning_key, winning_key]
    assert [path.name for path in storage.root.glob("*.docx")] == [winning_key]


def test_capability_target_generation_has_single_external_owner(db, monkeypatch):
    user = _user("capability-claim")
    job = _job(user.id, "capability-claim-job")
    resume = Resume(
        id="capability-claim-resume",
        user_id=user.id,
        original_file_key="unused.docx",
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="简历",
    )
    match = Match(
        id="capability-claim-match",
        user_id=user.id,
        resume_id=resume.id,
        job_id=job.id,
        total_score=50,
        recommendation="consider",
        dimension_scores_json={},
        evidence_json=[],
        gaps_json=[{"requirement": "测试"}],
        confirmations_json=[],
        ai_explanation_json={},
    )
    db.add(user)
    db.flush()
    db.add_all([job, resume])
    db.flush()
    db.add(match)
    db.commit()

    generator_entered = Event()
    release_generator = Event()
    calls = 0
    calls_lock = Lock()

    async def fake_build(*_args, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        generator_entered.set()
        await asyncio.to_thread(release_generator.wait, 5)
        return (
            [
                {
                    "requirement": "测试",
                    "category": "skills",
                    "severity": "medium",
                    "jd_evidence": "负责测试流程",
                    "deliverable": "完成测试报告",
                    "acceptance_criteria_json": ["报告可打开"],
                    "estimated_hours": 2,
                }
            ],
            "fake",
        )

    monkeypatch.setattr(workflow, "build_targets", fake_build)
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    start = Barrier(2)

    def create() -> str:
        with Session() as session:
            current_user = session.get(User, user.id)
            start.wait(timeout=5)
            try:
                asyncio.run(
                    workflow.create_capability_targets(
                        match.id,
                        user=current_user,
                        db=session,
                    )
                )
                return "created"
            except AppError as exc:
                if exc.code == "CAPABILITY_TARGET_GENERATION_IN_PROGRESS":
                    release_generator.set()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create) for _ in range(2)]
        assert generator_entered.wait(timeout=5)
        results = [future.result(timeout=10) for future in futures]

    assert calls == 1
    assert sorted(results) == ["CAPABILITY_TARGET_GENERATION_IN_PROGRESS", "created"]
    db.expire_all()
    assert db.scalar(select(func.count(CapabilityTarget.id))) == 1
    assert db.get(CapabilityTargetRun, match.id).status == "completed"
