from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import current_user
from app.errors import AppError
from app.models.entities import AuditLog, User, UserProfile
from app.security import create_token, hash_password, verify_password
from .common import dump


router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class LoginIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str


def set_session(response: Response, user: User):
    settings = get_settings()
    response.set_cookie(
        settings.auth_cookie_name,
        create_token(user.id),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )


@router.post("/register", status_code=201)
async def register(data: RegisterIn, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email.lower())):
        raise AppError("EMAIL_ALREADY_REGISTERED", "该邮箱已注册。", 409)
    now = datetime.now(timezone.utc)
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        last_active_at=now,
        retention_expires_at=now + timedelta(days=get_settings().data_retention_days),
    )
    db.add(user)
    db.flush()
    db.add(UserProfile(user_id=user.id))
    db.add(
        AuditLog(
            actor_user_id=user.id, action="auth.register", entity_type="user", entity_id=user.id
        )
    )
    db.commit()
    set_session(response, user)
    return dump(user, {"password_hash"})


@router.post("/login")
async def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "邮箱或密码错误。", 401)
    if user.status not in {"active", "deletion_requested"}:
        raise AppError("ACCOUNT_NOT_ACTIVE", "账号当前不可登录。", 403)
    if user.status == "active":
        now = datetime.now(timezone.utc)
        user.last_active_at = now
        if user.role == "user":
            user.retention_expires_at = now + timedelta(days=get_settings().data_retention_days)
        db.commit()
    set_session(response, user)
    return dump(user, {"password_hash"})


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(get_settings().auth_cookie_name)


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return dump(user, {"password_hash"})


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password", status_code=204)
async def change_password(
    data: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if not verify_password(data.current_password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "当前密码错误。", 400)
    user.password_hash = hash_password(data.new_password)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="auth.password_changed",
            entity_type="user",
            entity_id=user.id,
        )
    )
    db.commit()


account_router = APIRouter(prefix="/api", tags=["account"])


@account_router.delete("/account", status_code=202)
async def request_deletion(user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    user.status = "deletion_requested"
    user.deletion_requested_at = now
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="account.deletion_requested",
            entity_type="user",
            entity_id=user.id,
        )
    )
    db.commit()
    return {"status": "deletion_requested"}
