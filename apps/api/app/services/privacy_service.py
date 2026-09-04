from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AdvisorAssignment,
    Application,
    ApplicationChannel,
    ApplicationChannelReport,
    ApplicationEvent,
    AuditLog,
    CampusAnnouncement,
    CapabilityTarget,
    CapabilityTargetRun,
    ExperienceEntry,
    Interview,
    Job,
    Match,
    Notification,
    Order,
    QuotaLedger,
    QuotaReservation,
    Resume,
    ResumeFact,
    ResumeVersion,
    User,
    UserProfile,
)
from app.providers.storage.local import LocalStorage
from app.services.job_access import owned_job_clause
from app.services.storage_cleanup import enqueue_file_deletions, process_storage_deletions


def purge_user_data(
    db: Session,
    user: User,
    storage: LocalStorage,
    *,
    audit_action: str = "account.purged",
    actor_user_id: str | None = None,
    audit_metadata: dict | None = None,
) -> dict[str, int]:
    """Atomically anonymize account data, audit it, and schedule file deletion."""
    purge_owner_ids = db.info.setdefault("pii_purge_owner_ids", set())
    purge_owner_ids.add(user.id)
    try:
        return _purge_user_data(
            db,
            user,
            storage,
            audit_action=audit_action,
            actor_user_id=actor_user_id,
            audit_metadata=audit_metadata,
        )
    finally:
        purge_owner_ids.discard(user.id)
        if not purge_owner_ids:
            db.info.pop("pii_purge_owner_ids", None)


def _purge_user_data(
    db: Session,
    user: User,
    storage: LocalStorage,
    *,
    audit_action: str,
    actor_user_id: str | None,
    audit_metadata: dict | None,
) -> dict[str, int]:
    """Internal purge body; the public wrapper grants the explicit DB-write scope."""
    now = datetime.now(timezone.utc)
    file_keys: list[str] = []
    owned_entity_ids = {user.id}

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
        profile.consent_version = ""
        profile.consented_at = None

    resumes = list(db.scalars(select(Resume).where(Resume.user_id == user.id)))
    owned_entity_ids.update(resume.id for resume in resumes)
    for resume in resumes:
        if resume.original_file_key:
            file_keys.append(resume.original_file_key)
        resume.original_file_key = ""
        resume.original_media_type = ""
        resume.display_name = "已删除简历"
        resume.parsed_text = ""
        resume.contact_json = {}
        resume.missing_information_json = []
        resume.parse_status = "failed"
        resume.facts_confirmed_at = None
        resume.deleted_at = now

    targets = list(db.scalars(select(CapabilityTarget).where(CapabilityTarget.user_id == user.id)))
    owned_entity_ids.update(target.id for target in targets)
    for target in targets:
        db.delete(target)
    db.flush()

    private_experience = list(
        db.scalars(select(ExperienceEntry).where(ExperienceEntry.owner_user_id == user.id))
    )
    owned_entity_ids.update(entry.id for entry in private_experience)
    for entry in private_experience:
        db.delete(entry)
    db.flush()

    facts = list(db.scalars(select(ResumeFact).where(ResumeFact.user_id == user.id)))
    owned_entity_ids.update(fact.id for fact in facts)
    for fact in facts:
        db.delete(fact)

    versions = list(db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user.id)))
    owned_entity_ids.update(version.id for version in versions)
    for version in versions:
        if version.export_file_key:
            file_keys.append(version.export_file_key)
        version.title = "已删除定制简历"
        version.content_json = {}
        version.traceability_json = {}
        version.export_file_key = ""
        version.guard_status = "blocked"
        version.unachieved_count = 0
        version.review_status = "rejected"
        version.reviewed_by = None
        version.reviewed_at = None

    jobs = list(db.scalars(select(Job).where(owned_job_clause(user.id))))
    owned_entity_ids.update(job.id for job in jobs)
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
        job.channel_id = None
        job.announcement_id = None

    matches = list(db.scalars(select(Match).where(Match.user_id == user.id)))
    owned_entity_ids.update(match.id for match in matches)
    for match in matches:
        match.total_score = 0
        match.recommendation = ""
        match.dimension_scores_json = {}
        match.evidence_json = []
        match.gaps_json = []
        match.confirmations_json = []
        match.ai_explanation_json = {}

    target_runs = list(
        db.scalars(select(CapabilityTargetRun).where(CapabilityTargetRun.user_id == user.id))
    )
    for target_run in target_runs:
        db.delete(target_run)

    applications = list(db.scalars(select(Application).where(Application.user_id == user.id)))
    owned_entity_ids.update(application.id for application in applications)
    application_ids = [application.id for application in applications]
    application_events: list[ApplicationEvent] = []
    if application_ids:
        application_events = list(
            db.scalars(
                select(ApplicationEvent).where(
                    ApplicationEvent.application_id.in_(application_ids)
                )
            )
        )
        owned_entity_ids.update(event.id for event in application_events)
        for event in application_events:
            event.note = ""
    for application in applications:
        application.channel_id = None
        application.source_url = ""
        application.notes = ""
        application.status = "withdrawn"
        application.user_confirmed_at = None
        application.applied_at = None
        application.last_response_at = None
        application.next_action_at = None

    private_announcements = list(
        db.scalars(
            select(CampusAnnouncement).where(CampusAnnouncement.owner_user_id == user.id)
        )
    )
    owned_entity_ids.update(item.id for item in private_announcements)
    for item in private_announcements:
        db.delete(item)

    # Global channels, shared campus announcements and experience templates are
    # company/example data and stay outside personal retention cleanup.
    # Only user-owned channel rows are removed when that owner deletes the account.
    private_channels = list(
        db.scalars(
            select(ApplicationChannel).where(ApplicationChannel.owner_user_id == user.id)
        )
    )
    owned_entity_ids.update(channel.id for channel in private_channels)
    for channel in private_channels:
        db.delete(channel)

    channel_reports = list(
        db.scalars(
            select(ApplicationChannelReport).where(ApplicationChannelReport.user_id == user.id)
        )
    )
    affected_channel_ids = {report.channel_id for report in channel_reports}
    for report in channel_reports:
        db.delete(report)
    db.flush()
    for channel_id in affected_channel_ids:
        channel = db.get(ApplicationChannel, channel_id)
        if channel is None:
            continue
        remaining_reports = len(
            list(
                db.scalars(
                    select(ApplicationChannelReport.id).where(
                        ApplicationChannelReport.channel_id == channel_id
                    )
                )
            )
        )
        channel.dead_reports = max(
            remaining_reports,
            max(0, channel.dead_reports - 1),
        )
        if channel.dead_reports < 3 and channel.verify_status == "dead":
            channel.verify_status = "unverified"

    interviews = list(db.scalars(select(Interview).where(Interview.user_id == user.id)))
    owned_entity_ids.update(interview.id for interview in interviews)
    for interview in interviews:
        interview.scheduled_at = None
        interview.question_set_json = {}
        interview.answers_json = {}
        interview.scorecard_json = {}
        interview.feedback_json = {}
        interview.advisor_id = None
        interview.status = "deleted"

    notifications = list(db.scalars(select(Notification).where(Notification.user_id == user.id)))
    owned_entity_ids.update(notification.id for notification in notifications)
    for notification in notifications:
        db.delete(notification)

    assignments = list(
        db.scalars(select(AdvisorAssignment).where(AdvisorAssignment.user_id == user.id))
    )
    owned_entity_ids.update(assignment.id for assignment in assignments)
    for assignment in assignments:
        assignment.status = "ended"
        assignment.ended_at = now

    ledgers = list(db.scalars(select(QuotaLedger).where(QuotaLedger.user_id == user.id)))
    owned_entity_ids.update(ledger.id for ledger in ledgers)
    reservations = list(
        db.scalars(select(QuotaReservation).where(QuotaReservation.user_id == user.id))
    )
    for reservation in reservations:
        db.delete(reservation)
    db.flush()
    for ledger in ledgers:
        ledger.reason = "账号删除后保留的额度审计记录"
        ledger.reference_id = ""

    orders = list(db.scalars(select(Order).where(Order.user_id == user.id)))
    owned_entity_ids.update(order.id for order in orders)
    for order in orders:
        order.provider_order_id = ""

    # Audit ownership is either direct authorship or a reference to any entity owned by
    # the user. Retain the event skeleton, but remove free-form metadata and IP material.
    related_audit_logs = list(
        db.scalars(
            select(AuditLog).where(
                or_(
                    AuditLog.actor_user_id == user.id,
                    AuditLog.entity_id.in_(owned_entity_ids),
                )
            )
        )
    )
    for audit_log in related_audit_logs:
        audit_log.metadata_json = {}
        audit_log.ip_hash = ""

    user.status = "deleted"
    user.deleted_at = now
    user.retention_expires_at = now
    user.last_active_at = None
    user.deletion_requested_at = None
    user.email = f"deleted-{user.id}@example.invalid"
    user.display_name = "已删除用户"
    user.password_hash = "account-deleted"
    user.timezone = "UTC"

    scheduled_file_keys = enqueue_file_deletions(db, file_keys)
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=audit_action,
            entity_type="user",
            entity_id=user.id,
            metadata_json={
                **(audit_metadata or {}),
                "files_scheduled": len(scheduled_file_keys),
            },
        )
    )

    # The audit record and durable file locators commit in the exact same transaction
    # as anonymization. Physical deletion happens only after those references are safe.
    db.commit()
    try:
        deletion = process_storage_deletions(
            db,
            storage,
            file_keys=scheduled_file_keys,
            limit=max(1, len(scheduled_file_keys)),
        )
    except Exception:
        # Anonymization and the locator queue are already durable. A transient
        # cleanup/query failure must not turn a successful purge into an API 500.
        db.rollback()
        deletion = {
            "files_removed": 0,
            "files_delete_failed": len(scheduled_file_keys),
        }

    return {
        **deletion,
        "capability_targets_removed": len(targets),
        "facts_removed": len(facts),
        "notifications_removed": len(notifications),
        "private_channels_removed": len(private_channels),
        "channel_reports_removed": len(channel_reports),
        "target_runs_removed": len(target_runs),
        "audit_logs_scrubbed": len(related_audit_logs),
    }
