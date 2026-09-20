from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import require_roles
from app.models.entities import InviteCode, User
from app.services.invite_service import create_invite, revoke_invite

from .common import dump, listed

router = APIRouter(prefix="/api/admin/invites", tags=["admin"])


class InviteIn(BaseModel):
    label: str = Field(default="", max_length=100)
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def _invite_view(row: InviteCode) -> dict:
    # code_hash is deliberately excluded: it is an internal lookup value.
    return dump(row, {"code_hash"})


@router.post("", status_code=201)
async def create(
    data: InviteIn,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    expires_in_days = data.expires_in_days or settings.invite_default_expires_days
    row, code = create_invite(
        db,
        actor,
        label=data.label,
        max_uses=data.max_uses,
        expires_in_days=expires_in_days,
    )
    # The plaintext code is returned exactly once and never persisted.
    return {**_invite_view(row), "code": code}


@router.get("")
async def index(
    actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    rows = db.scalars(select(InviteCode).order_by(InviteCode.created_at.desc())).all()
    return listed([_invite_view(row) for row in rows])


@router.post("/{invite_id}/revoke")
async def revoke(
    invite_id: str,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    return _invite_view(revoke_invite(db, actor, invite_id))
