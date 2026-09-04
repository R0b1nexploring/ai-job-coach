import logging
import re
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import current_user
from app.errors import AppError
from app.models.entities import (
    AuditLog,
    Job,
    Match,
    Resume,
    ResumeFact,
    User,
    UserProfile,
)
from app.providers.jobs import discover_jobs
from app.providers.jobs.base import MAX_RAW_JD_CHARS
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import (
    JobStructuredOutput,
    MatchExplanationOutput,
    ResumeAnalysisOutput,
    ResumeExtractionOutput,
)
from app.providers.storage.runtime import get_storage
from app.services.channel_sources import allowed_job_source_hosts
from app.services.experience_service import (
    LIBRARY_PARSE_STATUS,
    sync_confirmed_facts_to_experience,
)
from app.services.job_access import visible_job
from app.services.job_normalizer import ground_job_output, normalize_job
from app.services.matcher import score_match
from app.services.provider_status import provider_status
from app.services.quota_service import change, request_fingerprint
from app.services.resume_analyzer import analyze_resume
from app.services.resume_parser import (
    ALLOWED,
    build_missing_information,
    deterministic_extraction,
    parse_resume,
    sanitize_extraction,
)
from app.services.storage_cleanup import (
    enqueue_file_deletions,
    process_storage_deletions,
    schedule_and_process_file_deletions,
)

from .common import dump, listed

router = APIRouter(prefix="/api", tags=["core"])
logger = logging.getLogger("app.core")
UPLOAD_READ_CHUNK_BYTES = 64 * 1024


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read incrementally and stop as soon as the configured limit is crossed."""
    content = bytearray()
    while chunk := await file.read(UPLOAD_READ_CHUNK_BYTES):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise AppError(
                "FILE_TOO_LARGE",
                f"文件不能超过 {max_bytes // (1024 * 1024)}MB。",
                413,
            )
    return bytes(content)


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {
        "status": "ok",
        "application": "ok",
        "database": "ok",
        "providers": provider_status(),
    }


class ProfileIn(BaseModel):
    school: str = ""
    major: str = ""
    graduation_year: int | None = None
    education_level: str = ""
    target_cities: list[str] = []
    target_roles: list[str] = []
    target_industries: list[str] = []
    salary_min: int | None = None
    salary_max: int | None = None
    accepts_shift: bool | None = None
    accepts_travel: bool | None = None
    accepts_factory: bool | None = None
    notes: str = ""
    consent: bool = False


@router.get("/profile")
async def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.get(UserProfile, user.id) or UserProfile(user_id=user.id)
    data = dump(profile)
    for key in ["cities", "roles", "industries"]:
        data[f"target_{key}"] = data.pop(f"target_{key}_json")
    return data


@router.put("/profile")
async def save_profile(
    data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    profile = db.get(UserProfile, user.id) or UserProfile(user_id=user.id)
    for field in [
        "school",
        "major",
        "graduation_year",
        "education_level",
        "salary_min",
        "salary_max",
        "accepts_shift",
        "accepts_travel",
        "accepts_factory",
        "notes",
    ]:
        setattr(profile, field, getattr(data, field))
    profile.target_cities_json = data.target_cities
    profile.target_roles_json = data.target_roles
    profile.target_industries_json = data.target_industries
    if data.consent:
        profile.consented_at = datetime.now(timezone.utc)
    db.add(profile)
    db.commit()
    return await get_profile(user, db)


@router.post("/resumes", status_code=201)
async def upload_resume(
    file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)
):
    settings = get_settings()
    max_bytes = max(0, settings.max_upload_mb) * 1024 * 1024
    content = await _read_upload_limited(file, max_bytes)
    text_value, _preliminary_facts = parse_resume(
        content, file.content_type or "", file.filename or "resume"
    )
    fallback = deterministic_extraction(text_value)
    structured, provider_name = await generate_structured(
        task="resume_extract",
        system_prompt=(
            "你是简历事实抽取器。text 和 source_text 必须逐字来自输入原文，不得润色；"
            "日期、组织、职位和地点不确定时留空，绝不猜测。按给定结构输出严格 JSON。"
        ),
        user_payload={"resume_text": text_value, "mock_response": fallback},
        response_model=ResumeExtractionOutput,
    )
    extraction = sanitize_extraction(structured.model_dump(), text_value)
    fallback_extraction = sanitize_extraction(fallback, text_value)
    if not extraction["facts"]:
        extraction = fallback_extraction
        if provider_name == "compatible":
            provider_name = "mock_fallback"
    else:
        for field, value in fallback_extraction["contact"].items():
            extraction["contact"][field] = extraction["contact"].get(field) or value
    suffix = ALLOWED[file.content_type]
    storage = get_storage()
    key = storage.save(content, suffix)
    try:
        resume = Resume(
            user_id=user.id,
            original_file_key=key,
            original_media_type=file.content_type or "",
            display_name=(file.filename or "简历")[:200],
            parse_status="parsed",
            parsed_text=text_value,
            parser_version=f"2.0:{provider_name}",
            contact_json=extraction["contact"],
        )
        db.add(resume)
        db.flush()
        created_facts = []
        for fact in extraction["facts"]:
            row = ResumeFact(resume_id=resume.id, user_id=user.id, created_by=user.id, **fact)
            db.add(row)
            db.flush()
            created_facts.append(row)
        resume.missing_information_json = build_missing_information(created_facts)
        db.commit()
    except Exception:
        db.rollback()
        try:
            schedule_and_process_file_deletions(
                db.get_bind(),
                storage,
                file_keys=[key],
            )
        except Exception as cleanup_error:
            logger.error(
                "resume_upload_cleanup_schedule_failed error_type=%s",
                type(cleanup_error).__name__,
            )
        raise
    return dump(resume, {"original_file_key", "parsed_text"})


@router.get("/resumes")
async def resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Resume)
        .where(
            Resume.user_id == user.id,
            Resume.deleted_at.is_(None),
            Resume.parse_status != LIBRARY_PARSE_STATUS,
        )
        .order_by(Resume.created_at.desc())
    ).all()
    return listed([dump(x, {"original_file_key", "parsed_text"}) for x in rows])


def owned_resume(db, user, resume_id):
    row = db.scalar(
        select(Resume).where(
            Resume.id == resume_id, Resume.user_id == user.id, Resume.deleted_at.is_(None)
        )
    )
    if not row:
        raise AppError("RESUME_NOT_FOUND", "简历不存在。", 404)
    return row


@router.get("/resumes/{resume_id}")
async def resume_detail(
    resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return dump(owned_resume(db, user, resume_id), {"original_file_key"})


@router.delete("/resumes/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_resume(db, user, resume_id)
    file_key = row.original_file_key
    row.deleted_at = datetime.now(timezone.utc)
    scheduled = enqueue_file_deletions(db, [file_key])
    db.commit()
    try:
        process_storage_deletions(
            db,
            get_storage(),
            file_keys=scheduled,
            limit=max(1, len(scheduled)),
        )
    except Exception as cleanup_error:
        # The database and durable locator are already committed. A later
        # maintenance pass can retry without resurrecting the deleted resume.
        db.rollback()
        logger.error(
            "resume_delete_storage_cleanup_processing_failed error_type=%s",
            type(cleanup_error).__name__,
        )


@router.get("/resumes/{resume_id}/facts")
async def facts(resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_resume(db, user, resume_id)
    rows = db.scalars(
        select(ResumeFact).where(ResumeFact.resume_id == resume_id, ResumeFact.user_id == user.id)
    ).all()
    return listed([dump(x) for x in rows])


class FactIn(BaseModel):
    label: str | None = None
    value_json: dict | None = None


class FactCreateIn(BaseModel):
    category: str = Field(default="other", min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=200)
    value_json: dict
    source_text: str = Field(default="", max_length=5000)
    source_location: str = Field(default="用户补充", max_length=100)


class ClarificationAnswerIn(BaseModel):
    fact_id: str
    field: Literal["organization", "role_title", "location", "start_date", "end_date"]
    value: str = Field(min_length=1, max_length=200)


def owned_fact(db, user, fact_id):
    row = db.scalar(
        select(ResumeFact).where(ResumeFact.id == fact_id, ResumeFact.user_id == user.id)
    )
    if not row:
        raise AppError("FACT_NOT_FOUND", "事实不存在。", 404)
    return row


def refresh_resume_confirmation(db: Session, resume_id: str) -> None:
    resume = db.get(Resume, resume_id)
    if not resume:
        return
    has_pending = db.scalar(
        select(ResumeFact.id).where(
            ResumeFact.resume_id == resume_id,
            ResumeFact.user_id == resume.user_id,
            ResumeFact.verification_status.in_(["extracted", "proposed"]),
        )
    )
    has_confirmed = db.scalar(
        select(ResumeFact.id).where(
            ResumeFact.resume_id == resume_id,
            ResumeFact.user_id == resume.user_id,
            ResumeFact.verification_status == "user_confirmed",
        )
    )
    resume.facts_confirmed_at = (
        datetime.now(timezone.utc) if has_confirmed and not has_pending else None
    )


@router.post("/resumes/{resume_id}/facts", status_code=201)
async def create_fact(
    resume_id: str,
    data: FactCreateIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    resume = owned_resume(db, user, resume_id)
    row = ResumeFact(
        resume_id=resume.id,
        user_id=user.id,
        category=data.category,
        label=data.label,
        value_json=data.value_json,
        source_text=data.source_text,
        source_location=data.source_location,
        verification_status="proposed",
        provenance="user_added",
        created_by=user.id,
    )
    resume.facts_confirmed_at = None
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="resume_fact.created",
            entity_type="resume_fact",
            entity_id=row.id,
            metadata_json={"category": row.category},
        )
    )
    db.commit()
    return dump(row)


@router.patch("/resume-facts/{fact_id}")
async def edit_fact(
    fact_id: str, data: FactIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_fact(db, user, fact_id)
    if data.label is not None:
        row.label = data.label
    if data.value_json is not None:
        row.value_json = data.value_json
    row.verification_status = "extracted"
    row.confirmed_at = None
    resume = db.get(Resume, row.resume_id)
    if resume:
        resume.facts_confirmed_at = None
    db.commit()
    return dump(row)


@router.post("/resume-facts/{fact_id}/confirm")
async def confirm_fact(
    fact_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_fact(db, user, fact_id)
    row.verification_status = "user_confirmed"
    row.confirmed_at = datetime.now(timezone.utc)
    db.flush()
    refresh_resume_confirmation(db, row.resume_id)
    resume = db.get(Resume, row.resume_id)
    if resume:
        sync_confirmed_facts_to_experience(db, user, resume)
    db.commit()
    return dump(row)


@router.post("/resume-facts/{fact_id}/reject")
async def reject_fact(
    fact_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_fact(db, user, fact_id)
    row.verification_status = "user_rejected"
    row.confirmed_at = None
    db.flush()
    refresh_resume_confirmation(db, row.resume_id)
    db.commit()
    return dump(row)


@router.post("/resumes/{resume_id}/confirm-facts")
async def confirm_all_facts(
    resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_resume(db, user, resume_id)
    pending_facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == row.id,
                ResumeFact.user_id == user.id,
                ResumeFact.verification_status.in_(["extracted", "proposed"]),
            )
        )
    )
    has_confirmed = db.scalar(
        select(ResumeFact.id).where(
            ResumeFact.resume_id == row.id,
            ResumeFact.user_id == user.id,
            ResumeFact.verification_status == "user_confirmed",
        )
    )
    if not pending_facts and not has_confirmed:
        raise AppError(
            "RESUME_FACTS_EMPTY",
            "请至少保留并确认一条真实事实后再继续。",
            409,
        )
    missing = build_missing_information(pending_facts)
    if missing:
        raise AppError(
            "RESUME_FACTS_INCOMPLETE",
            "工作或项目经历缺少关键信息，请先补充后再批量确认。",
            409,
            {"missing_information": missing},
        )
    for fact in pending_facts:
        fact.verification_status = "user_confirmed"
        fact.confirmed_at = datetime.now(timezone.utc)
    row.facts_confirmed_at = datetime.now(timezone.utc)
    sync_confirmed_facts_to_experience(db, user, row)
    row.missing_information_json = build_missing_information(
        list(
            db.scalars(
                select(ResumeFact).where(
                    ResumeFact.resume_id == row.id,
                    ResumeFact.user_id == user.id,
                    ResumeFact.verification_status != "user_rejected",
                )
            )
        )
    )
    db.commit()
    return {"status": "confirmed"}


@router.post("/resumes/{resume_id}/answer-clarifications")
async def answer_clarifications(
    resume_id: str,
    data: list[ClarificationAnswerIn],
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    resume = owned_resume(db, user, resume_id)
    if not data:
        raise AppError("CLARIFICATION_REQUIRED", "请至少填写一项待补信息。", 422)
    updated = []
    for answer in data:
        fact = db.scalar(
            select(ResumeFact).where(
                ResumeFact.id == answer.fact_id,
                ResumeFact.resume_id == resume.id,
                ResumeFact.user_id == user.id,
            )
        )
        if not fact:
            raise AppError("FACT_NOT_FOUND", "事实不存在。", 404)
        value = answer.value.strip()
        if answer.field in {"start_date", "end_date"} and not _valid_answered_date(
            value, allow_present=answer.field == "end_date"
        ):
            raise AppError(
                "INVALID_FACT_DATE",
                "日期请使用 YYYY-MM、YYYY-MM-DD，结束时间也可填写“至今”。",
                422,
            )
        setattr(fact, answer.field, "至今" if value == "现在" else value)
        fact.verification_status = "extracted"
        fact.confirmed_at = None
        updated.append(fact)
    resume.facts_confirmed_at = None
    all_facts = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == resume.id,
                ResumeFact.user_id == user.id,
                ResumeFact.verification_status != "user_rejected",
            )
        )
    )
    resume.missing_information_json = build_missing_information(all_facts)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="resume.clarifications_answered",
            entity_type="resume",
            entity_id=resume.id,
            metadata_json={"updated_count": len(updated)},
        )
    )
    db.commit()
    return {
        "items": [dump(fact) for fact in updated],
        "missing_information": resume.missing_information_json,
    }


def _valid_answered_date(value: str, *, allow_present: bool) -> bool:
    if allow_present and value in {"至今", "现在"}:
        return True
    if not re.fullmatch(r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])(?:-[0-3]\d)?", value):
        return False
    if len(value) == 10:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
    return True


@router.post("/resumes/{resume_id}/analysis")
async def resume_analysis(
    resume_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    resume = owned_resume(db, user, resume_id)
    fact_rows = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == resume.id, ResumeFact.user_id == user.id
            )
        )
    )
    profile = db.get(UserProfile, user.id)
    fallback = analyze_resume(fact_rows, profile)
    structured, provider_name = await generate_structured(
        task="resume_analysis",
        system_prompt=(
            "你是简历方向分析助手。只能基于输入的简历事实和用户偏好提出探索建议；"
            "不得把未经确认信息写成已验证事实，不得虚构经验、数字或职业结论。输出严格 JSON。"
        ),
        user_payload={
            "facts": [
                {
                    "id": fact.id,
                    "status": fact.verification_status,
                    "category": fact.category,
                    "value": fact.value_json,
                }
                for fact in fact_rows
                if fact.verification_status != "user_rejected"
            ],
            "profile": {
                "target_roles": list(getattr(profile, "target_roles_json", []) or []),
                "target_cities": list(getattr(profile, "target_cities_json", []) or []),
            },
            "mock_response": fallback,
        },
        response_model=ResumeAnalysisOutput,
    )
    result = structured.model_dump()
    result["missing_information"] = list(resume.missing_information_json or [])
    valid_ids = {fact.id for fact in fact_rows if fact.verification_status != "user_rejected"}
    for suggestion in result["role_suggestions"]:
        suggestion["evidence_fact_ids"] = [
            fact_id for fact_id in suggestion["evidence_fact_ids"] if fact_id in valid_ids
        ]
    result.update(
        {
            "provider": provider_name,
            "analysis_status": "advisory_not_verified",
            "requires_fact_confirmation": any(
                fact.verification_status not in {"user_confirmed", "user_rejected"}
                for fact in fact_rows
            ),
        }
    )
    return result


class JobIn(BaseModel):
    raw_jd: str = Field(min_length=10, max_length=MAX_RAW_JD_CHARS)
    title: str = Field(default="", max_length=200)
    company_name: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=100)
    source_url: str = Field(default="", max_length=2048)
    published_at: datetime | None = None


class JobDiscoveryIn(BaseModel):
    resume_id: str
    provider: str = Field(
        default="sample",
        pattern="^(sample|public_catalog|greenhouse|lever|public_jsonld)$",
    )
    source_key: str = Field(default="", max_length=2048)
    limit: int = Field(default=10, ge=1, le=30)


async def create_job(data: JobIn, user: User, db: Session):
    fallback = normalize_job(data.raw_jd, data.title, data.company_name, data.city)
    structured, _provider_name = await generate_structured(
        task="jd_normalize",
        system_prompt=(
            "你是岗位信息结构化助手。只提取输入 JD 中明确存在的信息；不确定字段必须列入 "
            "uncertain_fields，不得猜测公司、城市、发布日期或岗位要求。输出严格 JSON。"
        ),
        user_payload={
            "raw_jd": data.raw_jd,
            "provided_fields": {
                "title": data.title,
                "company_name": data.company_name,
                "city": data.city,
            },
            "mock_response": {
                key: value for key, value in fallback.items() if key != "content_hash"
            },
        },
        response_model=JobStructuredOutput,
    )
    value = ground_job_output(
        structured.model_dump(),
        raw_jd=data.raw_jd,
        title=data.title,
        company_name=data.company_name,
        city=data.city,
        fallback=fallback,
    )
    existing = db.scalar(
        select(Job).where(
            Job.created_by == user.id,
            Job.company_name == value["company_name"],
            Job.title == value["title"],
            Job.city == value["city"],
            Job.content_hash == value["content_hash"],
        )
    )
    if existing:
        return dump(existing, {"raw_jd"})
    job = Job(
        created_by=user.id,
        owner_user_id=user.id,
        raw_jd=data.raw_jd,
        source_url=data.source_url,
        source_type="user_url" if data.source_url else "manual",
        company_name=value["company_name"],
        title=value["title"],
        city=value["city"],
        responsibilities_json=value["responsibilities"],
        must_have_json=value["must_have"],
        nice_to_have_json=value["nice_to_have"],
        keywords_json=value["keywords"],
        work_conditions_json=value["work_conditions"],
        content_hash=value["content_hash"],
        published_at=data.published_at,
    )
    db.add(job)
    db.commit()
    return dump(job, {"raw_jd"})


@router.post("/jobs/manual", status_code=201)
async def manual_job(
    data: JobIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return await create_job(data, user, db)


@router.post("/jobs/import-text", status_code=201)
async def import_job(
    data: JobIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return await create_job(data, user, db)


@router.post("/jobs/discover", status_code=201)
async def discover_public_jobs(
    data: JobDiscoveryIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    resume = owned_resume(db, user, data.resume_id)
    if data.provider in {"greenhouse", "lever", "public_jsonld"} and not data.source_key:
        raise AppError("JOB_SOURCE_REQUIRED", "请输入企业公开招聘页标识或 URL。", 422)
    fact_rows = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == resume.id,
                ResumeFact.user_id == user.id,
                ResumeFact.verification_status != "user_rejected",
            )
        )
    )
    profile = db.get(UserProfile, user.id)
    analysis = analyze_resume(fact_rows, profile)
    keywords = list(
        dict.fromkeys(
            word
            for suggestion in analysis["role_suggestions"]
            for word in suggestion["search_keywords"]
            if word.strip()
        )
    )[:15]
    cities = list(getattr(profile, "target_cities_json", []) or [])
    discovered, fallback_used, source_error = await discover_jobs(
        provider=data.provider,
        source_key=data.source_key,
        keywords=keywords,
        cities=cities,
        limit=data.limit,
        allowed_hosts=(
            allowed_job_source_hosts(db, user.id)
            if data.provider == "public_jsonld"
            else None
        ),
    )
    saved = []
    for item in discovered:
        result = await create_job(
            JobIn(
                raw_jd=item.raw_jd,
                title=item.title,
                company_name=item.company_name,
                city=item.city,
                source_url=item.source_url,
                published_at=item.published_at,
            ),
            user,
            db,
        )
        row = db.get(Job, result["id"])
        if row:
            row.source_type = "sample" if item.provider == "sample" else "company_site"
            db.commit()
            result = dump(row, {"raw_jd"})
        result["discovery_provider"] = item.provider
        result["content_quality"] = item.content_quality
        result["matched_keywords"] = item.matched_keywords
        saved.append(result)
    return {
        "items": saved,
        "total": len(saved),
        "provider": data.provider,
        "fallback_used": fallback_used,
        "source_error": source_error,
        "search_keywords": keywords,
        "notice": "岗位来自公开企业招聘接口、白名单结构化招聘页或受控样例；"
        "入库内容仍需用户打开来源核对。",
    }


@router.get("/jobs")
async def jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Job).where(Job.created_by == user.id).order_by(Job.created_at.desc())
    ).all()
    return listed([dump(x, {"raw_jd"}) for x in rows])


def owned_job(db, user, job_id):
    row = db.scalar(select(Job).where(Job.id == job_id, Job.created_by == user.id))
    if not row:
        raise AppError("JOB_NOT_FOUND", "岗位不存在。", 404)
    return row


@router.get("/jobs/{job_id}")
async def job_detail(
    job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return dump(owned_job(db, user, job_id))


class JobPatch(BaseModel):
    title: str | None = None
    company_name: str | None = None
    city: str | None = None
    salary_text: str | None = None
    source_url: str | None = None
    status: str | None = None


@router.patch("/jobs/{job_id}")
async def update_job(
    job_id: str, data: JobPatch, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_job(db, user, job_id)
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    db.commit()
    return dump(row, {"raw_jd"})


@router.post("/jobs/{job_id}/expire")
async def expire_job(
    job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = owned_job(db, user, job_id)
    row.status = "expired"
    db.commit()
    return dump(row, {"raw_jd"})


class MatchIn(BaseModel):
    resume_id: str
    job_id: str


@router.post("/matches", status_code=201)
async def create_match(
    data: MatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    resume = owned_resume(db, user, data.resume_id)
    job = visible_job(db, user, data.job_id)
    existing_match = db.scalar(
        select(Match).where(
            Match.user_id == user.id,
            Match.resume_id == resume.id,
            Match.job_id == job.id,
        )
    )
    if existing_match:
        return dump(existing_match)
    profile = db.get(UserProfile, user.id)
    facts_list = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == resume.id, ResumeFact.user_id == user.id
            )
        )
    )
    library_resume = db.scalar(
        select(Resume).where(
            Resume.user_id == user.id,
            Resume.parse_status == LIBRARY_PARSE_STATUS,
            Resume.deleted_at.is_(None),
        )
    )
    if library_resume and library_resume.id != resume.id:
        facts_list.extend(
            list(
                db.scalars(
                    select(ResumeFact).where(
                        ResumeFact.resume_id == library_resume.id,
                        ResumeFact.user_id == user.id,
                    )
                )
            )
        )
    result = score_match(facts_list, job, profile)
    explanation, provider_name = await generate_structured(
        task="match_explain",
        system_prompt=(
            "你是求职匹配解释助手。分数和推荐结果由本地规则给定，不得修改。"
            "只解释已确认事实证据、能力缺口和待确认项，不得把未知信息写成事实。输出严格 JSON。"
        ),
        user_payload={
            "deterministic_result": result,
            "confirmed_facts": [
                {"id": fact.id, "value": fact.value_json}
                for fact in facts_list
                if fact.verification_status == "user_confirmed"
            ],
            "job": {
                "title": job.title,
                "company_name": job.company_name,
                "must_have": job.must_have_json,
                "keywords": job.keywords_json,
                "work_conditions": job.work_conditions_json,
            },
            "mock_response": {
                "summary": (
                    f"综合匹配 {result['total_score']} 分，建议：{result['recommendation']}。"
                ),
                "evidence_links": result["evidence"],
                "gaps": result["gaps"],
                "confirmations_needed": result["confirmations"],
            },
        },
        response_model=MatchExplanationOutput,
    )
    explanation_payload = explanation.model_dump()
    explanation_payload.update(
        {
            "provider": provider_name,
            "hard_block": result["hard_block"],
            "must_have_hit_rate": result["must_have_hit_rate"],
            "experience_months": result["experience_months"],
        }
    )
    match = Match(
        user_id=user.id,
        resume_id=resume.id,
        job_id=job.id,
        total_score=result["total_score"],
        recommendation=result["recommendation"],
        dimension_scores_json=result["dimension_scores"],
        evidence_json=result["evidence"],
        gaps_json=result["gaps"],
        confirmations_json=result["confirmations"],
        ai_explanation_json=explanation_payload,
    )
    db.add(match)
    try:
        # The database unique constraint is the concurrency backstop. Flush the
        # match before quota mutations so a losing concurrent request can roll
        # back cleanly without a second debit.
        db.flush()
    except IntegrityError:
        db.rollback()
        existing_match = db.scalar(
            select(Match).where(
                Match.user_id == user.id,
                Match.resume_id == resume.id,
                Match.job_id == job.id,
            )
        )
        if existing_match:
            return dump(existing_match)
        raise
    free_key = f"free-match:{user.id}"
    change(
        db,
        user_id=user.id,
        quota_type="match",
        delta=1,
        reason="免费诊断",
        idempotency_key=free_key,
        request_hash=request_fingerprint(
            {"operation": "match.free_grant", "user_id": user.id}
        ),
    )
    change(
        db,
        user_id=user.id,
        quota_type="match",
        delta=-1,
        reason="生成匹配报告",
        idempotency_key=f"match:{resume.id}:{job.id}",
        request_hash=request_fingerprint(
            {
                "operation": "match.create",
                "resume_id": resume.id,
                "job_id": job.id,
            }
        ),
    )
    db.commit()
    return dump(match)


@router.get("/matches")
async def matches(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return listed(
        [
            dump(x)
            for x in db.scalars(
                select(Match).where(Match.user_id == user.id).order_by(Match.created_at.desc())
            ).all()
        ]
    )


@router.get("/matches/{match_id}")
async def match_detail(
    match_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.scalar(select(Match).where(Match.id == match_id, Match.user_id == user.id))
    if not row:
        raise AppError("MATCH_NOT_FOUND", "匹配报告不存在。", 404)
    return dump(row)
