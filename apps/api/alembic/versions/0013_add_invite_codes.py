"""Add invite-only signup codes (hash only, never the plaintext code)."""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0013_add_invite_codes"
down_revision = "0012_add_unified_tasks"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "invite_codes" in set(inspect(bind).get_table_names()):
        return
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_invite_codes_code_hash",
        "invite_codes",
        ["code_hash"],
        unique=True,
    )


def downgrade():
    bind = op.get_bind()
    if "invite_codes" not in set(inspect(bind).get_table_names()):
        return
    op.drop_index("ix_invite_codes_code_hash", table_name="invite_codes")
    op.drop_table("invite_codes")
