"""Scope quota idempotency keys by user and quota type."""

from alembic import op
from sqlalchemy import inspect


revision = "0002_scope_quota_idempotency"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def upgrade():
    constraints = inspect(op.get_bind()).get_unique_constraints("quota_ledger")
    if any(
        constraint["column_names"] == ["user_id", "quota_type", "idempotency_key"]
        for constraint in constraints
    ):
        return
    legacy = next(
        constraint
        for constraint in constraints
        if constraint["column_names"] == ["idempotency_key"]
    )
    with op.batch_alter_table("quota_ledger", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint(legacy["name"] or "uq_quota_ledger_idempotency_key", type_="unique")
        batch.create_unique_constraint(
            "uq_quota_ledger_user_type_idempotency",
            ["user_id", "quota_type", "idempotency_key"],
        )


def downgrade():
    constraints = inspect(op.get_bind()).get_unique_constraints("quota_ledger")
    if any(
        constraint["column_names"] == ["idempotency_key"]
        for constraint in constraints
    ):
        return
    scoped = next(
        constraint
        for constraint in constraints
        if constraint["column_names"] == ["user_id", "quota_type", "idempotency_key"]
    )
    with op.batch_alter_table("quota_ledger", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint(scoped["name"] or "uq_quota_ledger_user_id", type_="unique")
        batch.create_unique_constraint(
            "uq_quota_ledger_idempotency_key",
            ["idempotency_key"],
        )
