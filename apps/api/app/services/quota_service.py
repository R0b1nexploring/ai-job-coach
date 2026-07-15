from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.entities import QuotaLedger


def balance(db: Session, user_id: str, quota_type: str) -> int:
    return (
        db.scalar(
            select(func.coalesce(func.sum(QuotaLedger.delta), 0)).where(
                QuotaLedger.user_id == user_id, QuotaLedger.quota_type == quota_type
            )
        )
        or 0
    )


def change(
    db: Session,
    *,
    user_id: str,
    quota_type: str,
    delta: int,
    reason: str,
    idempotency_key: str,
    order_id: str | None = None,
    reference_type: str = "",
    reference_id: str = "",
):
    existing = db.scalar(
        select(QuotaLedger).where(
            QuotaLedger.user_id == user_id,
            QuotaLedger.quota_type == quota_type,
            QuotaLedger.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing
    if delta < 0 and balance(db, user_id, quota_type) + delta < 0:
        raise AppError("QUOTA_EXHAUSTED", f"{quota_type} 额度不足，请购买套餐后重试。", 409)
    row = QuotaLedger(
        user_id=user_id,
        order_id=order_id,
        quota_type=quota_type,
        delta=delta,
        reason=reason,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.add(row)
    db.flush()
    return row
