import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Match(Base):
    __tablename__ = "matches"
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


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    base_resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
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


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    resume_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_versions.id"), nullable=True
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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
