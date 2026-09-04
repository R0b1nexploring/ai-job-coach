import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Role(str, enum.Enum):
    user = "user"
    advisor = "advisor"
    admin = "admin"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[str] = mapped_column(String(20), default=Role.user.value)
    status: Mapped[str] = mapped_column(String(30), default="active")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=now
    )
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    school: Mapped[str] = mapped_column(String(200), default="")
    major: Mapped[str] = mapped_column(String(200), default="")
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    education_level: Mapped[str] = mapped_column(String(50), default="")
    target_cities_json: Mapped[list] = mapped_column(JSON, default=list)
    target_roles_json: Mapped[list] = mapped_column(JSON, default=list)
    target_industries_json: Mapped[list] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepts_shift: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accepts_travel: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accepts_factory: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    consent_version: Mapped[str] = mapped_column(String(20), default="1.0")
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdvisorAssignment(Base):
    __tablename__ = "advisor_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    advisor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    original_file_key: Mapped[str] = mapped_column(String(255))
    original_media_type: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(200))
    parse_status: Mapped[str] = mapped_column(String(30), default="uploaded")
    parsed_text: Mapped[str] = mapped_column(Text, default="")
    parser_version: Mapped[str] = mapped_column(String(20), default="1.0")
    contact_json: Mapped[dict] = mapped_column(JSON, default=dict)
    missing_information_json: Mapped[list] = mapped_column(JSON, default=list)
    facts_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResumeFact(Base):
    __tablename__ = "resume_facts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(200))
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    organization: Mapped[str] = mapped_column(String(200), default="")
    role_title: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(100), default="")
    start_date: Mapped[str] = mapped_column(String(10), default="")
    end_date: Mapped[str] = mapped_column(String(10), default="")
    provenance: Mapped[str] = mapped_column(String(20), default="original_resume")
    source_text: Mapped[str] = mapped_column(Text, default="")
    source_location: Mapped[str] = mapped_column(String(100), default="")
    verification_status: Mapped[str] = mapped_column(String(30), default="extracted")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ExperienceEntry(Base):
    """A first-class internship or project in the experience library."""

    __tablename__ = "experience_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    organization: Mapped[str] = mapped_column(String(200), default="")
    role_title: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(100), default="")
    start_date: Mapped[str] = mapped_column(String(10), default="")
    end_date: Mapped[str] = mapped_column(String(10), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    bullets_json: Mapped[list] = mapped_column(JSON, default=list)
    skills_json: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="user_added")
    linked_resume_id: Mapped[str | None] = mapped_column(
        ForeignKey("resumes.id"), nullable=True
    )
    linked_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_facts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), default="")
    salary_text: Mapped[str] = mapped_column(String(100), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), default="manual")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    raw_jd: Mapped[str] = mapped_column(Text)
    responsibilities_json: Mapped[list] = mapped_column(JSON, default=list)
    must_have_json: Mapped[list] = mapped_column(JSON, default=list)
    nice_to_have_json: Mapped[list] = mapped_column(JSON, default=list)
    keywords_json: Mapped[list] = mapped_column(JSON, default=list)
    work_conditions_json: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("application_channels.id"), nullable=True, index=True
    )
    announcement_id: Mapped[str | None] = mapped_column(
        ForeignKey("campus_announcements.id"), nullable=True, index=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "resume_id",
            "job_id",
            name="uq_matches_user_resume_job",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    scoring_version: Mapped[str] = mapped_column(String(20), default="1.0")
    total_score: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(30))
    dimension_scores_json: Mapped[dict] = mapped_column(JSON)
    evidence_json: Mapped[list] = mapped_column(JSON)
    gaps_json: Mapped[list] = mapped_column(JSON)
    confirmations_json: Mapped[list] = mapped_column(JSON)
    ai_explanation_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CapabilityTarget(Base):
    """A JD requirement the user has not met yet, plus what would make it true."""

    __tablename__ = "capability_targets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    match_id: Mapped[str | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    requirement: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(50), default="skills")
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    jd_evidence: Mapped[str] = mapped_column(Text, default="")
    deliverable: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria_json: Mapped[list] = mapped_column(JSON, default=list)
    estimated_hours: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    achieved_fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_facts.id"), nullable=True
    )
    achieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CapabilityTargetRun(Base):
    """Atomic generation claim for one match's capability-target set."""

    __tablename__ = "capability_target_runs"
    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    claim_token: Mapped[str] = mapped_column(String(36), default=uid)
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(50), default="")
    last_error: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    base_resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    match_id: Mapped[str | None] = mapped_column(
        ForeignKey("matches.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="submittable")
    content_json: Mapped[dict] = mapped_column(JSON)
    traceability_json: Mapped[dict] = mapped_column(JSON)
    guard_status: Mapped[str] = mapped_column(String(20), default="pending")
    unachieved_count: Mapped[int] = mapped_column(Integer, default=0)
    review_status: Mapped[str] = mapped_column(String(30), default="draft")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_file_key: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ApplicationChannel(Base):
    """A company-level application entry point, not a job posting source."""

    __tablename__ = "application_channels"
    __table_args__ = (
        UniqueConstraint(
            "content_hash",
            name="uq_application_channels_content_hash",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    company_name: Mapped[str] = mapped_column(String(200))
    company_name_normalized: Mapped[str] = mapped_column(String(200))
    company_aliases_json: Mapped[list] = mapped_column(JSON, default=list)
    channel_type: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(1000), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    scope: Mapped[str] = mapped_column(String(20), default="both")
    regions_json: Mapped[list] = mapped_column(JSON, default=list)
    industries_json: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(200), default="")
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verify_status: Mapped[str] = mapped_column(String(20), default="unverified")
    dead_reports: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CampusAnnouncement(Base):
    """A campus recruiting announcement with apply links, not a third-party scrape."""

    __tablename__ = "campus_announcements"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_campus_announcements_content_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    company_name: Mapped[str] = mapped_column(String(200))
    company_name_normalized: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300), default="")
    cities_json: Mapped[list] = mapped_column(JSON, default=list)
    class_years_json: Mapped[list] = mapped_column(JSON, default=list)
    industry_tags_json: Mapped[list] = mapped_column(JSON, default=list)
    jobs_json: Mapped[list] = mapped_column(JSON, default=list)
    majors_json: Mapped[list] = mapped_column(JSON, default=list)
    announcement_url: Mapped[str] = mapped_column(String(1000), default="")
    apply_url: Mapped[str] = mapped_column(String(1000), default="")
    apply_email: Mapped[str] = mapped_column(String(320), default="")
    scale: Mapped[str] = mapped_column(String(50), default="")
    batch: Mapped[str] = mapped_column(String(50), default="")
    written_test: Mapped[str] = mapped_column(String(50), default="")
    company_description: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("application_channels.id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(200), default="")
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ApplicationChannelReport(Base):
    """One user's dead-link report for one shared application channel."""

    __tablename__ = "application_channel_reports"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "user_id",
            name="uq_application_channel_reports_channel_user",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("application_channels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    resume_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_versions.id"), nullable=True
    )
    channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("application_channels.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="pending_confirmation")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    user_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    resume_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_versions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    question_set_json: Mapped[dict] = mapped_column(JSON, default=dict)
    answers_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scorecard_json: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback_json: Mapped[dict] = mapped_column(JSON, default=dict)
    advisor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Package(Base):
    __tablename__ = "packages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column(Integer)
    billing_period: Mapped[str] = mapped_column(String(30))
    resume_quota: Mapped[int] = mapped_column(Integer, default=0)
    application_quota: Mapped[int] = mapped_column(Integer, default=0)
    interview_quota: Mapped[int] = mapped_column(Integer, default=0)
    features_json: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_number: Mapped[str] = mapped_column(String(30), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    package_snapshot_json: Mapped[dict] = mapped_column(JSON)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(10), default="CNY")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    payment_provider: Mapped[str] = mapped_column(String(30), default="disabled")
    provider_order_id: Mapped[str] = mapped_column(String(100), default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class QuotaLedger(Base):
    __tablename__ = "quota_ledger"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "quota_type",
            "idempotency_key",
            name="uq_quota_ledger_user_type_idempotency",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    quota_type: Mapped[str] = mapped_column(String(30))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    reference_type: Mapped[str] = mapped_column(String(50), default="")
    reference_id: Mapped[str] = mapped_column(String(100), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuotaBalance(Base):
    """Atomically updated quota total; the ledger remains the immutable audit trail."""

    __tablename__ = "quota_balances"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_quota_balances_nonnegative"),
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    quota_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class QuotaReservation(Base):
    """Lifecycle marker for quota debited before an external generation call."""

    __tablename__ = "quota_reservations"
    ledger_id: Mapped[str] = mapped_column(
        ForeignKey("quota_ledger.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    quota_type: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(Integer)
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StorageDeletionTask(Base):
    """Durable locator for a private file that still needs physical deletion."""

    __tablename__ = "storage_deletion_tasks"
    __table_args__ = (
        UniqueConstraint("file_key", name="uq_storage_deletion_tasks_file_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    file_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
