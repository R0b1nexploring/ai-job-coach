"""Add durable task snapshot, lease, and retry fields to resume generation runs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "0011_add_persistent_resume_task_fields"
down_revision = "0010_add_resume_bundles_and_interview_guides"
branch_labels = None
depends_on = None


TASK_COLUMNS = (
    ("task_type", sa.String(40), "resume_generation"),
    ("phase", sa.String(40), "queued"),
    ("input_snapshot_json", sa.JSON(), "{}"),
    ("result_resources_json", sa.JSON(), "{}"),
    ("public_error_code", sa.String(60), ""),
    ("attempts", sa.Integer(), "0"),
    ("retry_count", sa.Integer(), "0"),
    ("max_attempts", sa.Integer(), "3"),
    ("lease_expires_at", sa.DateTime(timezone=True), None),
    ("heartbeat_at", sa.DateTime(timezone=True), None),
)


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("resume_bundle_runs")}
    for name, type_, default in TASK_COLUMNS:
        if name in columns:
            continue
        kwargs = {"nullable": default is None}
        if default is not None:
            kwargs["server_default"] = sa.text("'" + default + "'") if isinstance(default, str) else str(default)
        op.add_column("resume_bundle_runs", sa.Column(name, type_, **kwargs))
    indexes = {index["name"] for index in inspect(bind).get_indexes("resume_bundle_runs")}
    if "ix_resume_bundle_runs_status_lease" not in indexes:
        op.create_index(
            "ix_resume_bundle_runs_status_lease",
            "resume_bundle_runs",
            ["status", "lease_expires_at"],
        )


def downgrade():
    bind = op.get_bind()
    indexes = {index["name"] for index in inspect(bind).get_indexes("resume_bundle_runs")}
    if "ix_resume_bundle_runs_status_lease" in indexes:
        op.drop_index("ix_resume_bundle_runs_status_lease", table_name="resume_bundle_runs")
    columns = {column["name"] for column in inspect(bind).get_columns("resume_bundle_runs")}
    for name, _type, _default in reversed(TASK_COLUMNS):
        if name in columns:
            op.drop_column("resume_bundle_runs", name)
