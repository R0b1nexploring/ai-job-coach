from sqlalchemy import select

from app.models.entities import (
    Application,
    ApplicationEvent,
    Interview,
    Job,
    Match,
    Notification,
    Resume,
    ResumeFact,
    ResumeVersion,
    User,
    UserProfile,
)
from app.providers.storage.local import LocalStorage
from app.security import hash_password
from conftest import register


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
    application = Application(
        user_id=user.id,
        job_id=job.id,
        resume_version_id=version.id,
        source_url="https://example.test/private",
        notes="私人投递备注",
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
    db.add_all([application, interview, notification])
    db.flush()
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
    assert exported_data["jobs"][0]["raw_jd"] == "包含用户备注的 JD"
    assert exported_data["interviews"][0]["answers_json"]["q1"] == "私人回答"
    assert "original_file_key" not in exported_data["resumes"][0]
    assert "export_file_key" not in exported_data["resume_versions"][0]
    assert client.delete("/api/account").status_code == 202

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
    response = client.post(f"/api/admin/accounts/{user.id}/purge")
    assert response.status_code == 200, response.text

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
    assert job.raw_jd == "" and job.source_url == ""
    assert match.evidence_json == [] and match.ai_explanation_json == {}
    assert version.content_json == {} and version.export_file_key == ""
    assert application.notes == "" and application.source_url == ""
    assert interview.answers_json == {} and interview.question_set_json == {}
    assert db.scalar(select(ResumeFact).where(ResumeFact.user_id == user.id)) is None
    assert db.scalar(select(Notification).where(Notification.user_id == user.id)) is None
    event = db.scalar(select(ApplicationEvent).where(ApplicationEvent.application_id == application.id))
    assert event.note == ""
    assert not storage.path(original_key).exists()
    assert not storage.path(export_key).exists()
