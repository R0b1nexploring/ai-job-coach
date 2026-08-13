from conftest import register
from sqlalchemy import select

from app.models.entities import (
    Application,
    ApplicationChannel,
    ApplicationEvent,
    AuditLog,
    CapabilityTarget,
    Interview,
    Job,
    Match,
    Notification,
    Resume,
    ResumeFact,
    ResumeVersion,
    StorageDeletionTask,
    User,
    UserProfile,
)
from app.providers.storage.local import LocalStorage
from app.security import hash_password
from app.services.privacy_service import purge_user_data


def test_admin_purge_removes_files_and_personal_content(client, db):
    user_data = register(client)
    user = db.get(User, user_data["id"])
    profile = db.get(UserProfile, user.id)
    profile.school = "示例学校"
    profile.notes = "包含个人偏好的备注"

    storage = LocalStorage()
    original_key = storage.save(b"private resume", ".docx")
    export_key = storage.save(b"derived resume", ".docx")
    resume = Resume(
        user_id=user.id,
        original_file_key=original_key,
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="private.docx",
        parse_status="parsed",
        parsed_text="个人简历全文",
        contact_json={"phone": "13800000000", "email": "private@example.test"},
        missing_information_json=[{"question": "请补充私人信息"}],
    )
    db.add(resume)
    db.flush()
    fact = ResumeFact(
        resume_id=resume.id,
        user_id=user.id,
        category="experience",
        label="私人经历",
        value_json={"text": "个人事实"},
        source_text="原文事实",
        created_by=user.id,
    )
    job = Job(
        created_by=user.id,
        company_name="目标公司",
        title="目标岗位",
        raw_jd="包含用户备注的 JD",
        source_url="https://example.test/private",
        content_hash="private-hash",
    )
    db.add_all([fact, job])
    db.flush()
    match = Match(
        user_id=user.id,
        resume_id=resume.id,
        job_id=job.id,
        total_score=60,
        recommendation="可以尝试",
        dimension_scores_json={"skills": 10},
        evidence_json=[{"text": "私人证据"}],
        gaps_json=[],
        confirmations_json=[],
        ai_explanation_json={"summary": "私人分析"},
    )
    version = ResumeVersion(
        user_id=user.id,
        base_resume_id=resume.id,
        job_id=job.id,
        title="私人定制简历",
        content_json={"headline": "私人标题"},
        traceability_json={"private": True},
        export_file_key=export_key,
    )
    db.add_all([match, version])
    db.flush()
    target = CapabilityTarget(
        user_id=user.id,
        job_id=job.id,
        match_id=match.id,
        requirement="私人学习目标",
        jd_evidence="私人岗位要求",
        deliverable="私人产出物",
        acceptance_criteria_json=["私人标准"],
        evidence_text="私人证据",
        achieved_fact_id=fact.id,
    )
    db.add(target)
    db.flush()
    target_id = target.id
    application = Application(
        user_id=user.id,
        job_id=job.id,
        resume_version_id=version.id,
        source_url="https://example.test/private",
        notes="私人投递备注",
    )
    global_channel = ApplicationChannel(
        company_name="公共公司",
        company_name_normalized="公共公司",
        channel_type="email",
        email="global@example.test",
        source="test",
        content_hash="global-channel-hash",
    )
    private_channel = ApplicationChannel(
        owner_user_id=user.id,
        company_name="私有公司",
        company_name_normalized="私有公司",
        channel_type="email",
        email="private@example.test",
        source="test",
        content_hash="private-channel-hash",
    )
    interview = Interview(
        user_id=user.id,
        job_id=job.id,
        resume_version_id=version.id,
        question_set_json={"questions": ["私人问题"]},
        answers_json={"q1": "私人回答"},
        feedback_json={"text": "私人反馈"},
    )
    notification = Notification(user_id=user.id, title="私人通知", body="通知正文")
    db.add_all([application, interview, notification, global_channel, private_channel])
    db.flush()
    related_audit = AuditLog(
        actor_user_id=None,
        action="resume_version.reviewed",
        entity_type="resume_version",
        entity_id=version.id,
        metadata_json={"note": "包含个人手机号 13800000000"},
        ip_hash="private-ip-hash",
    )
    unrelated_audit = AuditLog(
        actor_user_id=None,
        action="channel.verified",
        entity_type="application_channel",
        entity_id=global_channel.id,
        metadata_json={"source": "公开公司渠道"},
        ip_hash="public-ip-hash",
    )
    db.add_all([related_audit, unrelated_audit])
    db.add(
        ApplicationEvent(
            application_id=application.id,
            from_status=None,
            to_status="pending_confirmation",
            actor_user_id=user.id,
            note="私人事件备注",
        )
    )
    db.commit()

    assert storage.path(original_key).exists()
    assert storage.path(export_key).exists()
    exported = client.get("/api/account/export")
    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "private, no-store"
    assert "ai-job-coach-data.json" in exported.headers["content-disposition"]
    exported_data = exported.json()
    assert exported_data["profile"]["school"] == "示例学校"
    assert exported_data["resume_facts"][0]["source_text"] == "原文事实"
    assert exported_data["capability_targets"][0]["evidence_text"] == "私人证据"
    assert exported_data["jobs"][0]["raw_jd"] == "包含用户备注的 JD"
    assert exported_data["interviews"][0]["answers_json"]["q1"] == "私人回答"
    assert "original_file_key" not in exported_data["resumes"][0]
    assert "export_file_key" not in exported_data["resume_versions"][0]
    assert client.delete("/api/account").status_code == 202
    db.refresh(user)
    assert user.deletion_requested_at is not None

    admin = User(
        email="privacy-admin@example.test",
        password_hash=hash_password("Password123!"),
        display_name="管理员",
        role="admin",
    )
    db.add(admin)
    db.commit()
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": admin.email, "password": "Password123!"},
    )
    pending = client.get("/api/admin/accounts/deletion-requests")
    assert pending.status_code == 200
    assert pending.json()["total"] == 1
    assert pending.json()["items"][0]["id"] == user.id
    assert "password_hash" not in pending.json()["items"][0]
    response = client.post(f"/api/admin/accounts/{user.id}/purge")
    assert response.status_code == 200, response.text
    assert client.get("/api/admin/accounts/deletion-requests").json()["total"] == 0

    db.refresh(user)
    db.refresh(profile)
    db.refresh(resume)
    db.refresh(job)
    db.refresh(match)
    db.refresh(version)
    db.refresh(application)
    db.refresh(interview)
    assert user.status == "deleted" and user.password_hash == "account-deleted"
    assert profile.school == "" and profile.notes == ""
    assert resume.parsed_text == "" and resume.original_file_key == ""
    assert resume.contact_json == {} and resume.missing_information_json == []
    assert job.raw_jd == "" and job.source_url == ""
    assert match.evidence_json == [] and match.ai_explanation_json == {}
    assert version.content_json == {} and version.export_file_key == ""
    assert application.notes == "" and application.source_url == ""
    assert interview.answers_json == {} and interview.question_set_json == {}
    assert db.scalar(select(ResumeFact).where(ResumeFact.user_id == user.id)) is None
    assert db.scalar(select(CapabilityTarget).where(CapabilityTarget.id == target_id)) is None
    assert db.scalar(select(Notification).where(Notification.user_id == user.id)) is None
    assert db.get(ApplicationChannel, private_channel.id) is None
    assert db.get(ApplicationChannel, global_channel.id) is not None
    event = db.scalar(
        select(ApplicationEvent).where(ApplicationEvent.application_id == application.id)
    )
    assert event.note == ""
    db.refresh(related_audit)
    db.refresh(unrelated_audit)
    assert related_audit.metadata_json == {} and related_audit.ip_hash == ""
    assert unrelated_audit.metadata_json == {"source": "公开公司渠道"}
    assert unrelated_audit.ip_hash == "public-ip-hash"
    assert not storage.path(original_key).exists()
    assert not storage.path(export_key).exists()


def test_regular_user_cannot_list_deletion_requests(client):
    register(client)
    response = client.get("/api/admin/accounts/deletion-requests")
    assert response.status_code == 403


def test_file_delete_failure_does_not_restore_anonymized_database_content(client, db):
    user_data = register(client, email="orphaned-file@example.test")
    user = db.get(User, user_data["id"])
    resume = Resume(
        user_id=user.id,
        original_file_key="orphaned-private-file.docx",
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="private.docx",
        parse_status="parsed",
        parsed_text="不应恢复的简历正文",
        contact_json={"phone": "13800000000"},
        missing_information_json=[{"question": "私人澄清问题"}],
    )
    db.add(resume)
    db.commit()

    class FailingStorage:
        def delete(self, key: str) -> None:
            raise OSError(f"cannot delete {key}")

    summary = purge_user_data(db, user, FailingStorage())
    assert summary["files_removed"] == 0
    assert summary["files_delete_failed"] == 1
    deletion_task = db.scalar(
        select(StorageDeletionTask).where(
            StorageDeletionTask.file_key == "orphaned-private-file.docx"
        )
    )
    assert deletion_task is not None
    assert deletion_task.attempts == 1
    assert deletion_task.last_error == "OSError"

    # A later rollback cannot resurrect PII: anonymization was committed first.
    db.rollback()
    db.expire_all()
    stored_user = db.get(User, user.id)
    stored_resume = db.get(Resume, resume.id)
    assert stored_user.status == "deleted"
    assert stored_resume.parsed_text == ""
    assert stored_resume.contact_json == {}
    assert stored_resume.missing_information_json == []


def test_purge_audit_and_anonymization_roll_back_together(db, monkeypatch):
    user = User(
        email="atomic-purge@example.test",
        password_hash=hash_password("Password123!"),
        display_name="原始姓名",
    )
    db.add(user)
    db.commit()

    original_commit = db.commit

    def failing_commit():
        raise RuntimeError("simulated audit transaction failure")

    monkeypatch.setattr(db, "commit", failing_commit)
    try:
        try:
            purge_user_data(db, user, LocalStorage())
        except RuntimeError:
            pass
    finally:
        monkeypatch.setattr(db, "commit", original_commit)
    db.rollback()
    db.expire_all()

    stored = db.get(User, user.id)
    assert stored.status == "active"
    assert stored.display_name == "原始姓名"
    assert db.scalar(
        select(AuditLog).where(
            AuditLog.action == "account.purged", AuditLog.entity_id == user.id
        )
    ) is None


def test_post_commit_cleanup_failure_keeps_successful_purge_and_locator(db, monkeypatch):
    user = User(
        email="cleanup-retry@example.test",
        password_hash=hash_password("Password123!"),
        display_name="等待清理",
    )
    db.add(user)
    db.flush()
    resume = Resume(
        user_id=user.id,
        original_file_key="cleanup-retry.docx",
        original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        display_name="private.docx",
    )
    db.add(resume)
    db.commit()

    def failing_cleanup(*args, **kwargs):
        raise RuntimeError("cleanup database unavailable")

    monkeypatch.setattr("app.services.privacy_service.process_storage_deletions", failing_cleanup)
    summary = purge_user_data(db, user, LocalStorage())

    db.expire_all()
    assert summary["files_delete_failed"] == 1
    assert db.get(User, user.id).status == "deleted"
    assert db.scalar(
        select(StorageDeletionTask).where(StorageDeletionTask.file_key == "cleanup-retry.docx")
    ) is not None
