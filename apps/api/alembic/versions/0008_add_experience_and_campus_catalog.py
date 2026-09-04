"""Add experience library and shared campus announcement catalog."""

from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0008_add_experience_and_campus_catalog"
down_revision = "0007_harden_integrity"
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
                    "0008 migration produced foreign-key violations: "
                    + repr(violations[:10])
                )
    finally:
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "campus_announcements" not in tables:
        op.create_table(
            "campus_announcements",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("company_name", sa.String(200), nullable=False),
            sa.Column("company_name_normalized", sa.String(200), nullable=False),
            sa.Column("title", sa.String(300), nullable=False, server_default=""),
            sa.Column("cities_json", sa.JSON(), nullable=False),
            sa.Column("class_years_json", sa.JSON(), nullable=False),
            sa.Column("industry_tags_json", sa.JSON(), nullable=False),
            sa.Column("jobs_json", sa.JSON(), nullable=False),
            sa.Column("majors_json", sa.JSON(), nullable=False),
            sa.Column("announcement_url", sa.String(1000), nullable=False, server_default=""),
            sa.Column("apply_url", sa.String(1000), nullable=False, server_default=""),
            sa.Column("apply_email", sa.String(320), nullable=False, server_default=""),
            sa.Column("scale", sa.String(50), nullable=False, server_default=""),
            sa.Column("batch", sa.String(50), nullable=False, server_default=""),
            sa.Column("written_test", sa.String(50), nullable=False, server_default=""),
            sa.Column("company_description", sa.Text(), nullable=False, server_default=""),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "channel_id",
                sa.String(36),
                sa.ForeignKey("application_channels.id"),
                nullable=True,
            ),
            sa.Column("source", sa.String(200), nullable=False, server_default=""),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("content_hash", name="uq_campus_announcements_content_hash"),
        )
        op.create_index(
            "ix_campus_announcements_owner_user_id",
            "campus_announcements",
            ["owner_user_id"],
        )
        op.create_index(
            "ix_campus_announcements_created_by",
            "campus_announcements",
            ["created_by"],
        )
        op.create_index(
            "ix_campus_announcements_channel_id",
            "campus_announcements",
            ["channel_id"],
        )
    if "experience_entries" not in tables:
        op.create_table(
            "experience_entries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("organization", sa.String(200), nullable=False, server_default=""),
            sa.Column("role_title", sa.String(200), nullable=False, server_default=""),
            sa.Column("location", sa.String(100), nullable=False, server_default=""),
            sa.Column("start_date", sa.String(10), nullable=False, server_default=""),
            sa.Column("end_date", sa.String(10), nullable=False, server_default=""),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("bullets_json", sa.JSON(), nullable=False),
            sa.Column("skills_json", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="user_added"),
            sa.Column("linked_resume_id", sa.String(36), sa.ForeignKey("resumes.id"), nullable=True),
            sa.Column(
                "linked_fact_id",
                sa.String(36),
                sa.ForeignKey("resume_facts.id"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_experience_entries_owner_user_id",
            "experience_entries",
            ["owner_user_id"],
        )

    job_columns = {column["name"] for column in inspect(bind).get_columns("jobs")}
    with _sqlite_rebuild_window():
      with op.batch_alter_table("jobs") as batch:
        if "owner_user_id" not in job_columns:
            batch.add_column(sa.Column("owner_user_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_jobs_owner_user_id",
                "users",
                ["owner_user_id"],
                ["id"],
            )
            batch.create_index("ix_jobs_owner_user_id", ["owner_user_id"])
        if "channel_id" not in job_columns:
            batch.add_column(sa.Column("channel_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_jobs_channel_id",
                "application_channels",
                ["channel_id"],
                ["id"],
            )
            batch.create_index("ix_jobs_channel_id", ["channel_id"])
        if "announcement_id" not in job_columns:
            batch.add_column(sa.Column("announcement_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_jobs_announcement_id",
                "campus_announcements",
                ["announcement_id"],
                ["id"],
            )
            batch.create_index("ix_jobs_announcement_id", ["announcement_id"])
        if "source_updated_at" not in job_columns:
            batch.add_column(sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True))

    bind.execute(sa.text("UPDATE jobs SET owner_user_id = created_by WHERE owner_user_id IS NULL"))


def downgrade():
    bind = op.get_bind()
    job_columns = {column["name"] for column in inspect(bind).get_columns("jobs")}
    with _sqlite_rebuild_window():
      with op.batch_alter_table("jobs") as batch:
        if "source_updated_at" in job_columns:
            batch.drop_column("source_updated_at")
        if "announcement_id" in job_columns:
            batch.drop_index("ix_jobs_announcement_id")
            batch.drop_constraint("fk_jobs_announcement_id", type_="foreignkey")
            batch.drop_column("announcement_id")
        if "channel_id" in job_columns:
            batch.drop_index("ix_jobs_channel_id")
            batch.drop_constraint("fk_jobs_channel_id", type_="foreignkey")
            batch.drop_column("channel_id")
        if "owner_user_id" in job_columns:
            batch.drop_index("ix_jobs_owner_user_id")
            batch.drop_constraint("fk_jobs_owner_user_id", type_="foreignkey")
            batch.drop_column("owner_user_id")
    tables = set(inspect(bind).get_table_names())
    if "experience_entries" in tables:
        op.drop_index("ix_experience_entries_owner_user_id", table_name="experience_entries")
        op.drop_table("experience_entries")
    if "campus_announcements" in tables:
        op.drop_index("ix_campus_announcements_channel_id", table_name="campus_announcements")
        op.drop_index("ix_campus_announcements_created_by", table_name="campus_announcements")
        op.drop_index("ix_campus_announcements_owner_user_id", table_name="campus_announcements")
        op.drop_table("campus_announcements")
