from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import current_user
from app.errors import AppError
from app.models.entities import ResumeBundle, ResumeVersion, TargetProfile, User
from app.services.bundle_service import (
    create_bundle,
    dump_bundle,
    owned_bundle,
    process_bundle,
    regenerate_scope,
    requeue_bundle,
)
from app.services.resume_edit_service import lock_bullet, reorder_bullet
from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html
from app.services.interview_guide_service import (
    dump_guide,
    owned_guide,
    regenerate_guide,
    render_guide_html,
)
from app.services.pdf_export import export_pdf
from app.services.target_profile_service import (
    create_target_profile,
    dump_profile,
    list_profile_sources,
    owned_profile,
    refresh_profile_if_sources_changed,
)
from app.api.routes.workflow import html_security_headers

from .common import listed

router = APIRouter(prefix="/api", tags=["studio"])


class TargetProfileIn(BaseModel):
    mode: str = Field(pattern="^(single_jd|multi_jd)$")
    job_ids: list[str] = Field(min_length=1, max_length=10)


@router.post("/target-profiles", status_code=201)
async def create_profile(
    data: TargetProfileIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    profile = await create_target_profile(db, user, mode=data.mode, job_ids=data.job_ids)
    db.commit()
    db.refresh(profile)
    return dump_profile(profile, list_profile_sources(db, profile.id))


@router.get("/target-profiles")
async def list_profiles(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(TargetProfile)
            .where(TargetProfile.user_id == user.id)
            .order_by(TargetProfile.updated_at.desc())
        )
    )
    return listed(
        [dump_profile(row, list_profile_sources(db, row.id)) for row in rows],
        page_size=50,
    )


@router.get("/target-profiles/{profile_id}")
async def get_target_profile(
    profile_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    profile = owned_profile(db, user, profile_id)
    refresh_profile_if_sources_changed(db, profile)
    db.commit()
    db.refresh(profile)
    return dump_profile(profile, list_profile_sources(db, profile.id))


class BundleIn(BaseModel):
    base_resume_id: str | None = None
    target_profile_id: str

    def resolved_resume_id(self) -> str | None:
        value = (self.base_resume_id or "").strip()
        return value or None


class LockIn(BaseModel):
    bullet_id: str
    locked: bool = True


class ReorderIn(BaseModel):
    bullet_id: str
    direction: Literal["up", "down"]


class RegenerateIn(BaseModel):
    scope: str = Field(pattern="^(bullet|section|all)$")
    bullet_id: str | None = None
    section_name: str | None = None


def _studio_version(db: Session, user: User, version_id: str) -> ResumeVersion:
    row = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id, ResumeVersion.user_id == user.id
        )
    )
    if not row:
        raise AppError("RESUME_VERSION_NOT_FOUND", "简历版本不存在。", 404)
    if row.guard_status != "passed":
        raise AppError("FACT_GUARD_BLOCKED", "事实检查未通过，不能预览或下载。", 409)
    if (
        get_settings().resume_quality_gate_active()
        and (row.quality_report_json or {}).get("hard_passed") is not True
    ):
        raise AppError(
            "RESUME_QUALITY_GATE_BLOCKED",
            "质量硬门禁未通过，不能预览或下载。",
            409,
        )
    if row.bundle_id:
        bundle = db.get(ResumeBundle, row.bundle_id)
        if bundle and bundle.status not in {"ready", "degraded"}:
            raise AppError("RESUME_BUNDLE_NOT_READY", "简历包仍在生成中。", 409)
    return row


def _dump_version(row: ResumeVersion, *, include_content: bool = True) -> dict:
    report = dict(row.quality_report_json or {})
    report.pop("prompt", None)
    report.pop("model_prompt", None)
    payload = {
        "id": row.id,
        "bundle_id": row.bundle_id,
        "kind": row.kind,
        "title": row.title,
        "guard_status": row.guard_status,
        "content_hash": row.content_hash,
        "unachieved_count": row.unachieved_count,
        "quality_report_json": report,
        "template_snapshot_json": row.template_snapshot_json or {},
    }
    if include_content:
        payload["content_json"] = row.content_json
    return payload


@router.post("/resume-bundles", status_code=202)
async def create_resume_bundle(
    data: BundleIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    resume_id = data.resolved_resume_id()
    bundle = create_bundle(
        db,
        user,
        base_resume_id=resume_id,
        target_profile_id=data.target_profile_id,
        idempotency_key=idempotency_key,
    )
    db.commit()
    db.refresh(bundle)
    return dump_bundle(db, bundle)


@router.post("/resume-bundles/{bundle_id}/retry", status_code=202)
async def retry_resume_bundle(
    bundle_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    bundle = requeue_bundle(db, user, bundle_id)
    db.commit()
    db.refresh(bundle)
    return dump_bundle(db, bundle)


@router.post("/resume-bundles/{bundle_id}/process", status_code=202)
async def process_resume_bundle(
    bundle_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    bundle = owned_bundle(db, user, bundle_id)
    if get_settings().app_env.strip().lower() in {"production", "prod"}:
        # Production work is exclusively claimed by the independent worker.
        # Keep this legacy endpoint as a non-blocking compatibility response.
        return dump_bundle(db, bundle)
    await process_bundle(db, bundle_id)
    db.commit()
    bundle = owned_bundle(db, user, bundle_id)
    return dump_bundle(db, bundle)


@router.get("/resume-bundles")
async def list_resume_bundles(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(ResumeBundle)
            .where(ResumeBundle.user_id == user.id)
            .order_by(ResumeBundle.updated_at.desc())
        )
    )
    return listed([dump_bundle(db, row) for row in rows], page_size=20)


@router.get("/resume-bundles/{bundle_id}")
async def get_resume_bundle(
    bundle_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    bundle = owned_bundle(db, user, bundle_id)
    return dump_bundle(db, bundle)


@router.get("/resume-versions/{version_id}/studio")
async def studio_version(
    version_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id, ResumeVersion.user_id == user.id
        )
    )
    if not row:
        raise AppError("RESUME_VERSION_NOT_FOUND", "简历版本不存在。", 404)
    return _dump_version(row)


@router.post("/resume-versions/{version_id}/lock")
async def studio_lock(
    version_id: str,
    data: LockIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = lock_bullet(db, user, version_id, data.bullet_id, data.locked)
    db.commit()
    db.refresh(row)
    return _dump_version(row)


@router.post("/resume-versions/{version_id}/reorder")
async def studio_reorder(
    version_id: str,
    data: ReorderIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = reorder_bullet(db, user, version_id, data.bullet_id, data.direction)
    db.commit()
    db.refresh(row)
    return _dump_version(row)


@router.post("/resume-versions/{version_id}/regenerate")
async def studio_regenerate(
    version_id: str,
    data: RegenerateIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == version_id, ResumeVersion.user_id == user.id
        )
    )
    if not row or not row.bundle_id:
        raise AppError("RESUME_VERSION_NOT_FOUND", "简历版本不存在。", 404)
    updated = await regenerate_scope(
        db,
        user,
        row.bundle_id,
        version_id=version_id,
        scope=data.scope,
        bullet_id=data.bullet_id,
        section_name=data.section_name,
    )
    db.commit()
    db.refresh(updated)
    return _dump_version(updated)


@router.get("/resume-versions/{version_id}/studio-preview", response_class=HTMLResponse)
async def studio_preview(
    version_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = _studio_version(db, user, version_id)
    return HTMLResponse(
        render_resume_html(row.content_json, row.title, snapshot=row.template_snapshot_json),
        headers=html_security_headers("inline"),
    )


@router.get("/resume-versions/{version_id}/studio-download")
async def studio_download(
    version_id: str,
    format: Literal["docx", "html", "pdf"] = Query(default="docx"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = _studio_version(db, user, version_id)
    snapshot = row.template_snapshot_json or {}
    if format == "html":
        return HTMLResponse(
            render_resume_html(row.content_json, row.title, snapshot=snapshot),
            headers=html_security_headers('attachment; filename="resume.html"'),
        )
    if format == "pdf":
        content = await export_pdf(row.content_json, row.title, snapshot=snapshot)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="resume.pdf"'},
        )
    content = render_resume_docx(row.content_json, row.title, snapshot=snapshot)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="resume.docx"'},
    )


@router.get("/interview-guides/{guide_id}")
async def get_interview_guide(
    guide_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    guide = owned_guide(db, user, guide_id)
    version = db.get(ResumeVersion, guide.resume_version_id)
    if version is not None and guide.content_hash != version.content_hash and guide.status == "ready":
        guide.status = "stale"
        db.commit()
    return dump_guide(guide)


@router.post("/interview-guides/{guide_id}/regenerate")
async def regenerate_interview_guide(
    guide_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    guide = await regenerate_guide(db, user, guide_id)
    db.commit()
    db.refresh(guide)
    return dump_guide(guide)


@router.get("/interview-guides/{guide_id}/download", response_class=HTMLResponse)
async def download_interview_guide(
    guide_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    guide = owned_guide(db, user, guide_id)
    return HTMLResponse(
        content=render_guide_html(guide),
        headers=html_security_headers('attachment; filename="interview-guide.html"'),
    )
