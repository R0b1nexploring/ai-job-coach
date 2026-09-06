"""Add target profiles and atomic material claims."""

from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0009_add_target_profiles_and_material_claims"
down_revision = "0008_add_experience_and_campus_catalog"
branch_labels = None
depends_on = None


EXPERIENCE_COLUMNS = (
    ("details_json", sa.JSON(), "{}"),
    ("clarifications_json", sa.JSON(), "[]"),
    ("completeness_score", sa.Integer(), "0"),
    ("status", sa.String(20), "draft"),
)

FACT_COLUMNS = (
    ("material_id", sa.String(36), None),
    ("claim_type", sa.String(30), ""),
    ("evidence_json", sa.JSON(), "{}"),
)


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
                    "0009 migration produced foreign-key violations: "
                    + repr(violations[:10])
                )
    finally:
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "target_profiles" not in tables:
        op.create_table(
            "target_profiles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("title", sa.String(200), nullable=False, server_default=""),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("quality_metadata_json", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_target_profiles_user_id", "target_profiles", ["user_id"])
        op.create_index("ix_target_profiles_input_hash", "target_profiles", ["input_hash"])
    if "target_profile_sources" not in tables:
        op.create_table(
            "target_profile_sources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "target_profile_id",
                sa.String(36),
                sa.ForeignKey("target_profiles.id"),
                nullable=False,
            ),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
            sa.Column("raw_jd_snapshot", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "target_profile_id",
                "job_id",
                name="uq_target_profile_sources_profile_job",
            ),
        )
        op.create_index(
            "ix_target_profile_sources_target_profile_id",
            "target_profile_sources",
            ["target_profile_id"],
        )
        op.create_index(
            "ix_target_profile_sources_job_id",
            "target_profile_sources",
            ["job_id"],
        )

    experience_columns = {
        column["name"] for column in inspect(bind).get_columns("experience_entries")
    }
    for name, type_, default in EXPERIENCE_COLUMNS:
        if name not in experience_columns:
            kwargs = {"nullable": False}
            if default is not None:
                kwargs["server_default"] = default
            op.add_column("experience_entries", sa.Column(name, type_, **kwargs))

    fact_columns = {column["name"] for column in inspect(bind).get_columns("resume_facts")}
    with _sqlite_rebuild_window():
        with op.batch_alter_table("resume_facts") as batch:
            if "material_id" not in fact_columns:
                batch.add_column(sa.Column("material_id", sa.String(36), nullable=True))
                batch.create_foreign_key(
                    "fk_resume_facts_material_id",
                    "experience_entries",
                    ["material_id"],
                    ["id"],
                )
                batch.create_index("ix_resume_facts_material_id", ["material_id"])
            if "claim_type" not in fact_columns:
                batch.add_column(
                    sa.Column(
                        "claim_type",
                        sa.String(30),
                        nullable=False,
                        server_default="",
                    )
                )
            if "evidence_json" not in fact_columns:
                batch.add_column(
                    sa.Column(
                        "evidence_json",
                        sa.JSON(),
                        nullable=False,
                        server_default="{}",
                    )
                )

    bind.execute(
        sa.text(
            "UPDATE experience_entries SET status = 'confirmed' "
            "WHERE linked_fact_id IS NOT NULL AND TRIM(COALESCE(status, '')) IN ('', 'draft')"
        )
    )


def downgrade():
    bind = op.get_bind()
    fact_columns = {column["name"] for column in inspect(bind).get_columns("resume_facts")}
    with _sqlite_rebuild_window():
        with op.batch_alter_table("resume_facts") as batch:
            if "evidence_json" in fact_columns:
                batch.drop_column("evidence_json")
            if "claim_type" in fact_columns:
                batch.drop_column("claim_type")
            if "material_id" in fact_columns:
                batch.drop_index("ix_resume_facts_material_id")
                batch.drop_constraint("fk_resume_facts_material_id", type_="foreignkey")
                batch.drop_column("material_id")

    experience_columns = {
        column["name"] for column in inspect(bind).get_columns("experience_entries")
    }
    with op.batch_alter_table("experience_entries") as batch:
        for name, _type, _default in reversed(EXPERIENCE_COLUMNS):
            if name in experience_columns:
                batch.drop_column(name)

    tables = set(inspect(bind).get_table_names())
    if "target_profile_sources" in tables:
        op.drop_index(
            "ix_target_profile_sources_job_id", table_name="target_profile_sources"
        )
        op.drop_index(
            "ix_target_profile_sources_target_profile_id",
            table_name="target_profile_sources",
        )
        op.drop_table("target_profile_sources")
    if "target_profiles" in tables:
        op.drop_index("ix_target_profiles_input_hash", table_name="target_profiles")
        op.drop_index("ix_target_profiles_user_id", table_name="target_profiles")
        op.drop_table("target_profiles")
