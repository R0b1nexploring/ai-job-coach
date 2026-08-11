from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user
from app.errors import AppError
from app.models.entities import (
    Application,
    ApplicationChannel,
    Job,
    Resume,
    ResumeFact,
    ResumeVersion,
    User,
    UserProfile,
)
from app.services.application_email import build_email_draft
from app.services.channel_sources import invalidate_channel_host_cache, visible_channel_query

from .common import dump, listed
from .core import JobDiscoveryIn, discover_public_jobs

router = APIRouter(prefix="/api", tags=["channels"])


def owned_or_global_channel(db: Session, user: User, channel_id: str) -> ApplicationChannel:
    channel = db.scalar(
        select(ApplicationChannel).where(
            ApplicationChannel.id == channel_id,
            or_(
                ApplicationChannel.owner_user_id.is_(None),
                ApplicationChannel.owner_user_id == user.id,
            ),
        )
    )
    if not channel:
        raise AppError("CHANNEL_NOT_FOUND", "投递渠道不存在。", 404)
    return channel


@router.get("/channels")
async def channels(
    search: str = Query(default="", max_length=100),
    channel_type: str = Query(default="", pattern="^(|career_page|email|form)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    statement = visible_channel_query(user.id)
    if search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                ApplicationChannel.company_name.ilike(pattern),
                ApplicationChannel.company_name_normalized.ilike(pattern),
            )
        )
    if channel_type:
        statement = statement.where(ApplicationChannel.channel_type == channel_type)
    rows = list(db.scalars(statement.order_by(ApplicationChannel.company_name).limit(200)))
    return listed([dump(row) for row in rows], page_size=200)


class ChannelDiscoveryIn(BaseModel):
    resume_id: str
    limit: int = Field(default=10, ge=1, le=30)


@router.post("/channels/{channel_id}/discover-jobs", status_code=201)
async def discover_channel_jobs(
    channel_id: str,
    data: ChannelDiscoveryIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    channel = owned_or_global_channel(db, user, channel_id)
    if channel.channel_type != "career_page" or not channel.url:
        raise AppError("CHANNEL_NOT_DISCOVERABLE", "只有公司招聘页渠道可以读取结构化岗位。", 409)
    if channel.verify_status == "dead":
        raise AppError("CHANNEL_DEAD", "该投递渠道已标记失效，不能继续读取。", 409)
    return await discover_public_jobs(
        JobDiscoveryIn(
            resume_id=data.resume_id,
            provider="public_jsonld",
            source_key=channel.url,
            limit=data.limit,
        ),
        user,
        db,
    )


@router.post("/channels/{channel_id}/report-dead")
async def report_channel_dead(
    channel_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    channel = owned_or_global_channel(db, user, channel_id)
    channel.dead_reports += 1
    if channel.dead_reports >= 3:
        channel.verify_status = "dead"
    db.commit()
    if channel.verify_status == "dead":
        invalidate_channel_host_cache(db)
    return dump(channel)


@router.post("/applications/{application_id}/email-draft")
async def application_email_draft(
    application_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == user.id,
        )
    )
    if not application:
        raise AppError("APPLICATION_NOT_FOUND", "投递记录不存在。", 404)
    if not application.channel_id:
        raise AppError("APPLICATION_CHANNEL_REQUIRED", "请先为投递记录选择邮件渠道。", 409)
    channel = owned_or_global_channel(db, user, application.channel_id)
    if channel.channel_type != "email" or not channel.email:
        raise AppError("EMAIL_CHANNEL_REQUIRED", "该投递记录没有可用的邮件渠道。", 409)
    if not application.resume_version_id:
        raise AppError("RESUME_VERSION_REQUIRED", "生成邮件草稿前请先选择定制简历。", 409)
    version = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == application.resume_version_id,
            ResumeVersion.user_id == user.id,
        )
    )
    job = db.scalar(select(Job).where(Job.id == application.job_id, Job.created_by == user.id))
    if not version or not job:
        raise AppError("APPLICATION_CONTEXT_MISSING", "投递关联的岗位或简历不存在。", 409)
    resume = db.scalar(
        select(Resume).where(
            Resume.id == version.base_resume_id,
            Resume.user_id == user.id,
        )
    )
    facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == version.base_resume_id,
                ResumeFact.user_id == user.id,
            )
        )
    )
    profile = db.get(UserProfile, user.id)
    return await build_email_draft(
        profile,
        version,
        job,
        channel,
        facts=facts,
        contact=resume.contact_json if resume else {},
    )
