from fastapi import Cookie, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .errors import AppError
from .models.entities import AdvisorAssignment, User
from .security import decode_token


async def current_user(
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=get_settings().auth_cookie_name),
) -> User:
    user_id = decode_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if not user or user.status not in {"active", "deletion_requested"}:
        raise AppError("UNAUTHORIZED", "请先登录。", 401)
    return user


def require_roles(*roles: str):
    async def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise AppError("FORBIDDEN", "你没有执行此操作的权限。", 403)
        return user

    return dependency


def can_access_user(db: Session, actor: User, user_id: str) -> bool:
    if actor.role == "admin" or actor.id == user_id:
        return True
    if actor.role == "advisor":
        assignment = db.scalar(
            select(AdvisorAssignment).where(
                AdvisorAssignment.advisor_id == actor.id,
                AdvisorAssignment.user_id == user_id,
                AdvisorAssignment.status == "active",
            )
        )
        return assignment is not None
    return False
