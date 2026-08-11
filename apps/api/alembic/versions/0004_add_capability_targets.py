"""Add structured resume facts, capability targets and resume version kinds."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004_add_capability_targets"
down_revision = "0003_add_retention_fields"
branch_labels = None
depends_on = None

FACT_COLUMNS = (
    ("organization", sa.String(200), ""),
    ("role_title", sa.String(200), ""),
    ("location", sa.String(100), ""),
    ("start_date", sa.String(10), ""),
    ("end_date", sa.String(10), ""),
    ("provenance", sa.String(20), "original_resume"),
)

VERSION_COLUMNS = (
    ("kind", sa.String(20), "submittable"),
    ("unachieved_count", sa.Integer(), "0"),
)


def _add_missing(table: str, columns) -> None:
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns(table)}
    for name, type_, default in columns:
        if name in existing:
            continue
        op.add_column(
            table,
            sa.Column(name, type_, nullable=False, server_default=str(default)),
        )


def upgrade():
    _add_missing("resume_facts", FACT_COLUMNS)
    _add_missing("resume_versions", VERSION_COLUMNS)
    if "capability_targets" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "capability_targets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("match_id", sa.String(36), sa.ForeignKey("matches.id"), nullable=True),
            sa.Column("requirement", sa.String(300), nullable=False),
            sa.Column("category", sa.String(50), nullable=False, server_default="skills"),
            sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("jd_evidence", sa.Text(), nullable=False, server_default=""),
            sa.Column("deliverable", sa.Text(), nullable=False, server_default=""),
            sa.Column("acceptance_criteria_json", sa.JSON(), nullable=False),
            sa.Column("estimated_hours", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("evidence_text", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "achieved_fact_id", sa.String(36), sa.ForeignKey("resume_facts.id"), nullable=True
            ),
            sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_capability_targets_user_id", "capability_targets", ["user_id"])


def downgrade():
    if "capability_targets" in inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_capability_targets_user_id", table_name="capability_targets")
        op.drop_table("capability_targets")
    for table, columns in (("resume_versions", VERSION_COLUMNS), ("resume_facts", FACT_COLUMNS)):
        existing = {column["name"] for column in inspect(op.get_bind()).get_columns(table)}
        with op.batch_alter_table(table) as batch:
            for name, _type, _default in reversed(columns):
                if name in existing:
                    batch.drop_column(name)
