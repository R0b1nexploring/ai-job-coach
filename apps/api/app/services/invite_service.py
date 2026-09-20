import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.entities import AuditLog, InviteCode, User
from app.security import hash_invite_code


def create_invite(
    db: Session,
    actor: User,
    *,
    label: str,
    max_uses: int,
    expires_in_days: int,
) -> tuple[InviteCode, str]:
    """Create an invite and return it with the one-time plaintext code."""
    code = secrets.token_urlsafe(24)
    row = InviteCode(
        code_hash=hash_invite_code(code),
        label=label.strip()[:100],
        created_by=actor.id,
        max_uses=max_uses,
        used_count=0,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
    )
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action="invite.created",
            entity_type="invite_code",
            entity_id=row.id,
            metadata_json={"max_uses": max_uses, "expires_in_days": expires_in_days},
        )
    )
    db.commit()
    return row, code


def redeem_invite(db: Session, code: str) -> InviteCode:
    """Atomically consume one use of an invite.

    The conditional UPDATE is the concurrency authority on both SQLite and
    PostgreSQL; it participates in the caller's transaction so a failed signup
    rolls the redemption back.
    """
    now = datetime.now(UTC)
    code_hash = hash_invite_code(code)
    result = db.execute(
        update(InviteCode)
        .where(
            InviteCode.code_hash == code_hash,
            InviteCode.revoked_at.is_(None),
            InviteCode.expires_at > now,
            InviteCode.used_count < InviteCode.max_uses,
        )
        .values(used_count=InviteCode.used_count + 1)
    )
    if result.rowcount != 1:
        raise AppError("INVITE_INVALID", "邀请码无效、已过期或已用完。", 422)
    return db.scalar(select(InviteCode).where(InviteCode.code_hash == code_hash))


def revoke_invite(db: Session, actor: User, invite_id: str) -> InviteCode:
    row = db.get(InviteCode, invite_id)
    if row is None:
        raise AppError("INVITE_NOT_FOUND", "邀请码不存在。", 404)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.add(
            AuditLog(
                actor_user_id=actor.id,
                action="invite.revoked",
                entity_type="invite_code",
                entity_id=row.id,
            )
        )
        db.commit()
    return row
