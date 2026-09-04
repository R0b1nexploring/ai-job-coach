from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.entities import CampusAnnouncement, Job, User


def visible_job_clause(user_id: str):
    return or_(Job.owner_user_id.is_(None), Job.owner_user_id == user_id, Job.created_by == user_id)


def owned_job_clause(user_id: str):
    return or_(
        Job.owner_user_id == user_id,
        and_(
            Job.created_by == user_id,
            Job.owner_user_id.is_(None),
            Job.announcement_id.is_(None),
        ),
    )


def visible_announcement_clause(user_id: str):
    return or_(
        CampusAnnouncement.owner_user_id.is_(None),
        CampusAnnouncement.owner_user_id == user_id,
    )


def visible_job(db: Session, user: User, job_id: str) -> Job:
    row = db.scalar(select(Job).where(Job.id == job_id, visible_job_clause(user.id)))
    if not row:
        raise AppError("JOB_NOT_FOUND", "岗位不存在。", 404)
    return row


def visible_announcement(
    db: Session, user: User, announcement_id: str
) -> CampusAnnouncement:
    row = db.scalar(
        select(CampusAnnouncement).where(
            CampusAnnouncement.id == announcement_id,
            visible_announcement_clause(user.id),
        )
    )
    if not row:
        raise AppError("ANNOUNCEMENT_NOT_FOUND", "校招简章不存在。", 404)
    return row
