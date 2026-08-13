import hashlib
import json
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.entities import QuotaBalance, QuotaLedger


def request_fingerprint(payload: Any) -> str:
    """Return a stable, non-reversible fingerprint for an idempotent request."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def was_created(row: QuotaLedger) -> bool:
    """Whether this call inserted ``row`` rather than replaying an old one."""
    return bool(getattr(row, "_quota_change_created", False))


def balance(db: Session, user_id: str, quota_type: str) -> int:
    current = db.get(QuotaBalance, (user_id, quota_type))
    if current is not None:
        return current.balance
    # Compatibility for databases that have not yet materialized this pair.
    return max(0, _ledger_balance(db, user_id, quota_type))


def _ledger_balance(db: Session, user_id: str, quota_type: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(QuotaLedger.delta), 0)).where(
                QuotaLedger.user_id == user_id,
                QuotaLedger.quota_type == quota_type,
            )
        )
        or 0
    )


def _ensure_balance_row(db: Session, user_id: str, quota_type: str) -> None:
    values = {
        "user_id": user_id,
        "quota_type": quota_type,
        # Migration 0007 materializes all historical ledger pairs. A pair that
        # is absent here is therefore new and must start at zero. In
        # particular, do not SELECT the ledger before the write: that upgrade
        # from a read transaction is a common source of SQLITE_BUSY races.
        "balance": 0,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        statement = sqlite_insert(QuotaBalance).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "quota_type"]
        )
    elif dialect == "postgresql":
        statement = postgresql_insert(QuotaBalance).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "quota_type"]
        )
    else:
        if db.get(QuotaBalance, (user_id, quota_type)) is None:
            db.add(QuotaBalance(**values))
            db.flush()
        return
    db.execute(statement)


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
    request_hash: str | None = None,
):
    expected_hash = request_hash or request_fingerprint(
        {
            "delta": delta,
            "reason": reason,
            "order_id": order_id,
            "reference_type": reference_type,
            "reference_id": reference_id,
        }
    )

    def replay(existing: QuotaLedger) -> QuotaLedger:
        # Empty hashes are legacy rows created before request fingerprints were
        # introduced. They remain replayable for backwards compatibility.
        if existing.request_hash and existing.request_hash != expected_hash:
            raise AppError(
                "IDEMPOTENCY_KEY_REUSED",
                "该幂等键已用于不同的请求，请更换后重试。",
                409,
            )
        existing._quota_change_created = False
        return existing

    row = QuotaLedger(
        user_id=user_id,
        order_id=order_id,
        quota_type=quota_type,
        delta=delta,
        reason=reason,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        request_hash=expected_hash,
    )
    try:
        # Claim the unique ledger key *before* touching the cached balance.
        # Concurrent calls with the same key therefore serialize on that key
        # and replay the winner, even if only one unit remains. Different keys
        # then compete on the conditional UPDATE and cannot overdraw.
        with db.begin_nested():
            db.add(row)
            db.flush()
            _ensure_balance_row(db, user_id, quota_type)
            condition = [
                QuotaBalance.user_id == user_id,
                QuotaBalance.quota_type == quota_type,
            ]
            if delta < 0:
                condition.append(QuotaBalance.balance >= -delta)
            changed = db.execute(
                update(QuotaBalance)
                .where(*condition)
                .values(balance=QuotaBalance.balance + delta)
            )
            if changed.rowcount != 1:
                raise AppError(
                    "QUOTA_EXHAUSTED",
                    f"{quota_type} 额度不足，请购买套餐后重试。",
                    409,
                )
    except IntegrityError:
        existing = db.scalar(
            select(QuotaLedger).where(
                QuotaLedger.user_id == user_id,
                QuotaLedger.quota_type == quota_type,
                QuotaLedger.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return replay(existing)
        raise
    row._quota_change_created = True
    return row
