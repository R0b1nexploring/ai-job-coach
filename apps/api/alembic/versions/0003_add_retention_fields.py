"""Add explicit account retention lifecycle timestamps."""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "0003_add_retention_fields"
down_revision = "0002_scope_quota_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("users")}
    if "last_active_at" not in existing:
        op.add_column(
            "users", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "deletion_requested_at" not in existing:
        op.add_column(
            "users", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "retention_expires_at" not in existing:
        op.add_column(
            "users", sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
    users = sa.table(
        "users",
        sa.column("id", sa.String()),
        sa.column("role", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("last_active_at", sa.DateTime(timezone=True)),
        sa.column("deletion_requested_at", sa.DateTime(timezone=True)),
        sa.column("retention_expires_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    rows = bind.execute(
        sa.select(
            users.c.id,
            users.c.role,
            users.c.status,
            users.c.created_at,
            users.c.updated_at,
        )
    )
    for row in rows:
        active_at = row.updated_at or row.created_at or now
        values = {"last_active_at": active_at}
        if row.role == "user":
            values["retention_expires_at"] = active_at + timedelta(days=180)
        if row.status == "deletion_requested":
            values["deletion_requested_at"] = active_at
        bind.execute(sa.update(users).where(users.c.id == row.id).values(**values))


def downgrade():
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "retention_expires_at" in existing:
            batch.drop_column("retention_expires_at")
        if "deletion_requested_at" in existing:
            batch.drop_column("deletion_requested_at")
        if "last_active_at" in existing:
            batch.drop_column("last_active_at")
