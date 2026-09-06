"""Add resume bundles, generation runs, and interview guides."""

from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0010_add_resume_bundles_and_interview_guides"
down_revision = "0009_add_target_profiles_and_material_claims"
branch_labels = None
depends_on = None


@contextmanager
def _sqlite_rebuild_window():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        yield
        return
    context = op.get_context()
    with context.autocommit_block():
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        yield
        with context.autocommit_block():
            violations = list(bind.exec_driver_sql("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError(
                    "0010 migration produced foreign-key violations: "
                    + repr(violations[:10])
                )
    finally:
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "resume_bundles" not in tables:
        op.create_table(
            "resume_bundles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "base_resume_id",
                sa.String(36),
                sa.ForeignKey("resumes.id"),
                nullable=False,
            ),
            sa.Column(
                "target_profile_id",
                sa.String(36),
                sa.ForeignKey("target_profiles.id"),
                nullable=False,
            ),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("facts_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("target_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("template_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("idempotency_key", sa.String(200), nullable=False),
            sa.Column("generation_metadata_json", sa.JSON(), nullable=False),
            sa.Column("portrait_file_key", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "user_id",
                "idempotency_key",
                name="uq_resume_bundles_user_idempotency",
            ),
        )
        op.create_index("ix_resume_bundles_user_id", "resume_bundles", ["user_id"])
        op.create_index(
            "ix_resume_bundles_base_resume_id", "resume_bundles", ["base_resume_id"]
        )
        op.create_index(
            "ix_resume_bundles_target_profile_id",
            "resume_bundles",
            ["target_profile_id"],
        )
    if "resume_bundle_runs" not in tables:
        op.create_table(
            "resume_bundle_runs",
            sa.Column(
                "bundle_id",
                sa.String(36),
                sa.ForeignKey("resume_bundles.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("claim_token", sa.String(36), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("provider", sa.String(50), nullable=False, server_default=""),
            sa.Column("last_error", sa.String(200), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_resume_bundle_runs_user_id", "resume_bundle_runs", ["user_id"]
        )
    if "interview_guides" not in tables:
        op.create_table(
            "interview_guides",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "resume_version_id",
                sa.String(36),
                sa.ForeignKey("resume_versions.id"),
                nullable=False,
            ),
            sa.Column(
                "target_profile_id",
                sa.String(36),
                sa.ForeignKey("target_profiles.id"),
                nullable=False,
            ),
            sa.Column(
                "bundle_id",
                sa.String(36),
                sa.ForeignKey("resume_bundles.id"),
                nullable=True,
            ),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("content_json", sa.JSON(), nullable=False),
            sa.Column("quality_report_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_interview_guides_user_id", "interview_guides", ["user_id"])
        op.create_index(
            "ix_interview_guides_resume_version_id",
            "interview_guides",
            ["resume_version_id"],
        )
        op.create_index(
            "ix_interview_guides_target_profile_id",
            "interview_guides",
            ["target_profile_id"],
        )
        op.create_index(
            "ix_interview_guides_bundle_id", "interview_guides", ["bundle_id"]
        )

    version_columns = {
        column["name"] for column in inspect(bind).get_columns("resume_versions")
    }
    job_nullable = next(
        column["nullable"]
        for column in inspect(bind).get_columns("resume_versions")
        if column["name"] == "job_id"
    )
    with _sqlite_rebuild_window():
        with op.batch_alter_table("resume_versions") as batch:
            if "bundle_id" not in version_columns:
                batch.add_column(sa.Column("bundle_id", sa.String(36), nullable=True))
                batch.create_foreign_key(
                    "fk_resume_versions_bundle_id",
                    "resume_bundles",
                    ["bundle_id"],
                    ["id"],
                )
                batch.create_index("ix_resume_versions_bundle_id", ["bundle_id"])
            if "target_profile_id" not in version_columns:
                batch.add_column(
                    sa.Column("target_profile_id", sa.String(36), nullable=True)
                )
                batch.create_foreign_key(
                    "fk_resume_versions_target_profile_id",
                    "target_profiles",
                    ["target_profile_id"],
                    ["id"],
                )
                batch.create_index(
                    "ix_resume_versions_target_profile_id", ["target_profile_id"]
                )
            if "quality_report_json" not in version_columns:
                batch.add_column(
                    sa.Column(
                        "quality_report_json",
                        sa.JSON(),
                        nullable=False,
                        server_default="{}",
                    )
                )
            if "content_hash" not in version_columns:
                batch.add_column(
                    sa.Column(
                        "content_hash",
                        sa.String(64),
                        nullable=False,
                        server_default="",
                    )
                )
            if "template_snapshot_json" not in version_columns:
                batch.add_column(
                    sa.Column(
                        "template_snapshot_json",
                        sa.JSON(),
                        nullable=False,
                        server_default="{}",
                    )
                )
            if not job_nullable:
                batch.alter_column(
                    "job_id",
                    existing_type=sa.String(36),
                    nullable=True,
                )


def downgrade():
    bind = op.get_bind()
    version_columns = {
        column["name"] for column in inspect(bind).get_columns("resume_versions")
    }
    with _sqlite_rebuild_window():
        with op.batch_alter_table("resume_versions") as batch:
            if "template_snapshot_json" in version_columns:
                batch.drop_column("template_snapshot_json")
            if "content_hash" in version_columns:
                batch.drop_column("content_hash")
            if "quality_report_json" in version_columns:
                batch.drop_column("quality_report_json")
            if "target_profile_id" in version_columns:
                batch.drop_index("ix_resume_versions_target_profile_id")
                batch.drop_constraint(
                    "fk_resume_versions_target_profile_id", type_="foreignkey"
                )
                batch.drop_column("target_profile_id")
            if "bundle_id" in version_columns:
                batch.drop_index("ix_resume_versions_bundle_id")
                batch.drop_constraint("fk_resume_versions_bundle_id", type_="foreignkey")
                batch.drop_column("bundle_id")
            batch.alter_column(
                "job_id",
                existing_type=sa.String(36),
                nullable=False,
            )

    tables = set(inspect(bind).get_table_names())
    if "interview_guides" in tables:
        op.drop_index("ix_interview_guides_bundle_id", table_name="interview_guides")
        op.drop_index(
            "ix_interview_guides_target_profile_id", table_name="interview_guides"
        )
        op.drop_index(
            "ix_interview_guides_resume_version_id", table_name="interview_guides"
        )
        op.drop_index("ix_interview_guides_user_id", table_name="interview_guides")
        op.drop_table("interview_guides")
    if "resume_bundle_runs" in tables:
        op.drop_index("ix_resume_bundle_runs_user_id", table_name="resume_bundle_runs")
        op.drop_table("resume_bundle_runs")
    if "resume_bundles" in tables:
        op.drop_index(
            "ix_resume_bundles_target_profile_id", table_name="resume_bundles"
        )
        op.drop_index("ix_resume_bundles_base_resume_id", table_name="resume_bundles")
        op.drop_index("ix_resume_bundles_user_id", table_name="resume_bundles")
        op.drop_table("resume_bundles")
