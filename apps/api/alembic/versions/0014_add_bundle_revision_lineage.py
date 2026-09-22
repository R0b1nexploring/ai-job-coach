"""Add immutable revision lineage and metadata to resume bundles."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "0014_add_bundle_revision_lineage"
down_revision = "0013_add_invite_codes"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    columns = _columns("resume_bundles")
    with op.batch_alter_table("resume_bundles") as batch:
        if "parent_bundle_id" not in columns:
            batch.add_column(sa.Column("parent_bundle_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_resume_bundles_parent_bundle_id",
                "resume_bundles",
                ["parent_bundle_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "revision_json" not in columns:
            batch.add_column(
                sa.Column("revision_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
            )
    if "ix_resume_bundles_parent_bundle_id" not in _indexes("resume_bundles"):
        op.create_index(
            "ix_resume_bundles_parent_bundle_id",
            "resume_bundles",
            ["parent_bundle_id"],
        )


def downgrade():
    if "ix_resume_bundles_parent_bundle_id" in _indexes("resume_bundles"):
        op.drop_index("ix_resume_bundles_parent_bundle_id", table_name="resume_bundles")
    columns = _columns("resume_bundles")
    with op.batch_alter_table("resume_bundles") as batch:
        if "revision_json" in columns:
            batch.drop_column("revision_json")
        if "parent_bundle_id" in columns:
            batch.drop_constraint("fk_resume_bundles_parent_bundle_id", type_="foreignkey")
            batch.drop_column("parent_bundle_id")
