from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    AdvisorAssignment,
    Application,
    ApplicationEvent,
    Interview,
    Job,
    Match,
    Notification,
    QuotaLedger,
    Resume,
    ResumeFact,
    ResumeVersion,
    User,
    UserProfile,
)
from app.providers.storage.local import LocalStorage


def purge_user_data(db: Session, user: User, storage: LocalStorage) -> dict[str, int]:
    """Remove user content while retaining a minimal anonymized account/audit skeleton."""
    now = datetime.now(timezone.utc)
    files_removed = 0

    profile = db.get(UserProfile, user.id)
    if profile:
        profile.school = ""
        profile.major = ""
        profile.graduation_year = None
        profile.education_level = ""
        profile.target_cities_json = []
        profile.target_roles_json = []
        profile.target_industries_json = []
        profile.salary_min = None
        profile.salary_max = None
        profile.accepts_shift = None
        profile.accepts_travel = None
        profile.accepts_factory = None
        profile.notes = ""
        profile.consented_at = None

    resumes = list(db.scalars(select(Resume).where(Resume.user_id == user.id)))
    for resume in resumes:
        if resume.original_file_key:
            storage.delete(resume.original_file_key)
            files_removed += 1
        resume.original_file_key = ""
        resume.original_media_type = ""
        resume.display_name = "已删除简历"
        resume.parsed_text = ""
        resume.parse_status = "failed"
        resume.facts_confirmed_at = None
        resume.deleted_at = now

    facts = list(db.scalars(select(ResumeFact).where(ResumeFact.user_id == user.id)))
    for fact in facts:
        db.delete(fact)

    versions = list(db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user.id)))
    for version in versions:
        if version.export_file_key:
            storage.delete(version.export_file_key)
            files_removed += 1
        version.title = "已删除定制简历"
        version.content_json = {}
        version.traceability_json = {}
        version.export_file_key = ""
        version.guard_status = "blocked"
        version.review_status = "rejected"

    jobs = list(db.scalars(select(Job).where(Job.created_by == user.id)))
    for job in jobs:
        job.company_name = "已删除岗位"
        job.title = "已删除岗位"
        job.city = ""
        job.salary_text = ""
        job.source_url = ""
        job.raw_jd = ""
        job.responsibilities_json = []
        job.must_have_json = []
        job.nice_to_have_json = []
        job.keywords_json = []
        job.work_conditions_json = []
        job.content_hash = ""
        job.status = "closed"

    matches = list(db.scalars(select(Match).where(Match.user_id == user.id)))
    for match in matches:
        match.dimension_scores_json = {}
        match.evidence_json = []
        match.gaps_json = []
        match.confirmations_json = []
        match.ai_explanation_json = {}

    applications = list(db.scalars(select(Application).where(Application.user_id == user.id)))
    application_ids = [application.id for application in applications]
    if application_ids:
        for event in db.scalars(
            select(ApplicationEvent).where(ApplicationEvent.application_id.in_(application_ids))
        ):
            event.note = ""
    for application in applications:
        application.source_url = ""
        application.notes = ""
        application.status = "withdrawn"

    interviews = list(db.scalars(select(Interview).where(Interview.user_id == user.id)))
    for interview in interviews:
        interview.question_set_json = {}
        interview.answers_json = {}
        interview.scorecard_json = {}
        interview.feedback_json = {}
        interview.status = "deleted"

    notifications = list(db.scalars(select(Notification).where(Notification.user_id == user.id)))
    for notification in notifications:
        db.delete(notification)

    for assignment in db.scalars(
        select(AdvisorAssignment).where(AdvisorAssignment.user_id == user.id)
    ):
        assignment.status = "ended"
        assignment.ended_at = now

    for ledger in db.scalars(select(QuotaLedger).where(QuotaLedger.user_id == user.id)):
        ledger.reason = "账号删除后保留的额度审计记录"
        ledger.reference_id = ""

    user.status = "deleted"
    user.deleted_at = now
    user.retention_expires_at = now
    user.email = f"deleted-{user.id}@example.invalid"
    user.display_name = "已删除用户"
    user.password_hash = "account-deleted"

    return {
        "files_removed": files_removed,
        "facts_removed": len(facts),
        "notifications_removed": len(notifications),
    }
