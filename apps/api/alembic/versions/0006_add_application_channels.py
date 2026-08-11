"""Add company-level application channels and application linkage."""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0006_add_application_channels"
down_revision = "0005_add_resume_extraction_fields"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "application_channels" not in inspector.get_table_names():
        op.create_table(
            "application_channels",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("company_name", sa.String(200), nullable=False),
            sa.Column("company_name_normalized", sa.String(200), nullable=False),
            sa.Column("company_aliases_json", sa.JSON(), nullable=False),
            sa.Column("channel_type", sa.String(20), nullable=False),
            sa.Column("url", sa.String(1000), nullable=False, server_default=""),
            sa.Column("email", sa.String(320), nullable=False, server_default=""),
            sa.Column("scope", sa.String(20), nullable=False, server_default="both"),
            sa.Column("regions_json", sa.JSON(), nullable=False),
            sa.Column("industries_json", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(200), nullable=False, server_default=""),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verify_status", sa.String(20), nullable=False, server_default="unverified"),
            sa.Column("dead_reports", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "company_name_normalized",
                "channel_type",
                "url",
                "email",
                name="uq_application_channel_identity",
            ),
            sa.UniqueConstraint("content_hash", name="uq_application_channels_content_hash"),
        )
        op.create_index(
            "ix_application_channels_owner_user_id",
            "application_channels",
            ["owner_user_id"],
        )
        op.create_index(
            "ix_application_channels_content_hash",
            "application_channels",
            ["content_hash"],
        )
    application_columns = {
        column["name"] for column in inspect(op.get_bind()).get_columns("applications")
    }
    if "channel_id" not in application_columns:
        with op.batch_alter_table("applications") as batch:
            batch.add_column(sa.Column("channel_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_applications_channel_id",
                "application_channels",
                ["channel_id"],
                ["id"],
            )
            batch.create_index("ix_applications_channel_id", ["channel_id"])


def downgrade():
    application_columns = {
        column["name"] for column in inspect(op.get_bind()).get_columns("applications")
    }
    if "channel_id" in application_columns:
        with op.batch_alter_table("applications") as batch:
            batch.drop_index("ix_applications_channel_id")
            batch.drop_column("channel_id")
    if "application_channels" in inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_application_channels_content_hash", table_name="application_channels")
        op.drop_index("ix_application_channels_owner_user_id", table_name="application_channels")
        op.drop_table("application_channels")
