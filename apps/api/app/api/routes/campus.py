from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user
from app.models.entities import CampusAnnouncement, Job, User
from app.services.job_access import visible_announcement, visible_announcement_clause

from .common import dump

router = APIRouter(prefix="/api", tags=["campus"])


@router.get("/campus-announcements")
async def campus_announcements(
    q: str = Query(default="", max_length=100),
    city: str = Query(default="", max_length=50),
    hide_expired: bool = Query(default=True),
    page: int = Query(default=1, ge=1, le=200),
    page_size: int = Query(default=20, ge=1, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    statement = select(CampusAnnouncement).where(visible_announcement_clause(user.id))
    if q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                CampusAnnouncement.company_name.ilike(pattern),
                CampusAnnouncement.title.ilike(pattern),
            )
        )
    if city.strip():
        statement = statement.where(
            cast(CampusAnnouncement.cities_json, String).ilike(f"%{city.strip()}%")
        )
    if hide_expired:
        statement = statement.where(
            or_(
                CampusAnnouncement.expired_at.is_(None),
                CampusAnnouncement.expired_at >= datetime.now(timezone.utc),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.scalars(
            statement.order_by(
                CampusAnnouncement.published_at.desc(),
                CampusAnnouncement.created_at.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {
        "items": [_dump_announcement(db, row, include_jobs=True) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/campus-announcements/{announcement_id}")
async def campus_announcement_detail(
    announcement_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = visible_announcement(db, user, announcement_id)
    return _dump_announcement(db, row, include_jobs=True)


def _dump_announcement(db: Session, row: CampusAnnouncement, include_jobs: bool = False) -> dict:
    payload = dump(row)
    payload["expired"] = bool(
        row.expired_at and row.expired_at.replace(tzinfo=row.expired_at.tzinfo or timezone.utc)
        < datetime.now(timezone.utc)
    )
    payload["apply_kind"] = "email" if row.apply_email else ("url" if row.apply_url else "none")
    if include_jobs:
        jobs = list(
            db.scalars(
                select(Job)
                .where(Job.announcement_id == row.id)
                .order_by(Job.title)
            )
        )
        payload["jobs"] = [dump(job, {"raw_jd"}) for job in jobs]
    return payload
