from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import current_user
from app.errors import AppError
from app.models.entities import (
    AuditLog,
    Job,
    Match,
    QuotaLedger,
    Resume,
    ResumeFact,
    User,
    UserProfile,
)
from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import (
    JobStructuredOutput,
    MatchExplanationOutput,
    ResumeAnalysisOutput,
)
from app.providers.jobs import discover_jobs
from app.providers.storage.local import LocalStorage
from app.services.job_normalizer import normalize_job
from app.services.matcher import score_match
from app.services.quota_service import change
from app.services.resume_parser import ALLOWED, parse_resume
from app.services.resume_analyzer import analyze_resume
from app.services.provider_status import provider_status
from .common import dump, listed


router = APIRouter(prefix="/api", tags=["core"])


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
    content = await file.read()
    settings = get_settings()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", f"文件不能超过 {settings.max_upload_mb}MB。", 413)
    text_value, facts = parse_resume(content, file.content_type or "", file.filename or "resume")
    suffix = ALLOWED[file.content_type]
    key = LocalStorage().save(content, suffix)
    resume = Resume(
        user_id=user.id,
        original_file_key=key,
        original_media_type=file.content_type or "",
        display_name=(file.filename or "简历")[:200],
        parse_status="parsed",
        parsed_text=text_value,
    )
    db.add(resume)
    db.flush()
    for fact in facts:
        db.add(ResumeFact(resume_id=resume.id, user_id=user.id, created_by=user.id, **fact))
    db.commit()
    return dump(resume, {"original_file_key", "parsed_text"})


@router.get("/resumes")
async def resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Resume)
        .where(Resume.user_id == user.id, Resume.deleted_at.is_(None))
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
    row.deleted_at = datetime.now(timezone.utc)
    LocalStorage().delete(row.original_file_key)
    db.commit()


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
            ResumeFact.verification_status.in_(["extracted", "proposed"]),
        )
    )
    resume.facts_confirmed_at = None if has_pending else datetime.now(timezone.utc)


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
    for fact in db.scalars(
        select(ResumeFact).where(
            ResumeFact.resume_id == row.id,
            ResumeFact.user_id == user.id,
            ResumeFact.verification_status.in_(["extracted", "proposed"]),
        )
    ):
        fact.verification_status = "user_confirmed"
        fact.confirmed_at = datetime.now(timezone.utc)
    row.facts_confirmed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "confirmed"}


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
    raw_jd: str = Field(min_length=10)
    title: str = ""
    company_name: str = ""
    city: str = ""
    source_url: str = ""
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
    value = structured.model_dump()
    value["content_hash"] = fallback["content_hash"]
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
    job = owned_job(db, user, data.job_id)
    profile = db.get(UserProfile, user.id)
    facts_list = list(
        db.scalars(
            select(ResumeFact).where(
                ResumeFact.resume_id == resume.id, ResumeFact.user_id == user.id
            )
        )
    )
    free_key = f"free-match:{user.id}"
    if not db.scalar(
        select(QuotaLedger).where(
            QuotaLedger.user_id == user.id,
            QuotaLedger.quota_type == "match",
            QuotaLedger.idempotency_key == free_key,
        )
    ):
        change(
            db,
            user_id=user.id,
            quota_type="match",
            delta=1,
            reason="免费诊断",
            idempotency_key=free_key,
        )
    change(
        db,
        user_id=user.id,
        quota_type="match",
        delta=-1,
        reason="生成匹配报告",
        idempotency_key=f"match:{resume.id}:{job.id}",
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
    explanation_payload["provider"] = provider_name
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
