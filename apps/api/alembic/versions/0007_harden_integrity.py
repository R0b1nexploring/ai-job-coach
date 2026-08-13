"""Harden quota, match provenance, and channel identity invariants."""

import uuid
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0007_harden_integrity"
down_revision = "0006_add_application_channels"
branch_labels = None
depends_on = None


@contextmanager
def _sqlite_rebuild_window():
    """Allow Alembic batch table rebuilds while preserving FK verification.

    SQLite refuses to drop a referenced table while ``foreign_keys`` is on.
    Alembic batch mode necessarily performs that drop.  The PRAGMA cannot be
    changed inside a transaction, so use explicit autocommit windows and run
    ``foreign_key_check`` before restoring enforcement.
    """
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
                    "0007 migration produced foreign-key violations: "
                    + repr(violations[:10])
                )
    finally:
        with context.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def _unique_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_unique_constraints(table_name)
        if item.get("name")
    }


def _index_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def _deduplicate_matches() -> None:
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT id, user_id, resume_id, job_id "
                "FROM matches ORDER BY created_at, id"
            )
        ).mappings()
    )
    kept: dict[tuple[str, str, str], str] = {}
    for row in rows:
        identity = (row["user_id"], row["resume_id"], row["job_id"])
        keep_id = kept.setdefault(identity, row["id"])
        if keep_id == row["id"]:
            continue
        if "capability_targets" in inspect(bind).get_table_names():
            bind.execute(
                sa.text(
                    "UPDATE capability_targets SET match_id = :keep_id "
                    "WHERE match_id = :duplicate_id"
                ),
                {"keep_id": keep_id, "duplicate_id": row["id"]},
            )
        bind.execute(
            sa.text("DELETE FROM matches WHERE id = :duplicate_id"),
            {"duplicate_id": row["id"]},
        )


def _backfill_resume_version_matches() -> None:
    bind = op.get_bind()
    versions = list(
        bind.execute(
            sa.text(
                "SELECT id, user_id, base_resume_id, job_id "
                "FROM resume_versions WHERE match_id IS NULL"
            )
        ).mappings()
    )
    for version in versions:
        match_id = bind.execute(
            sa.text(
                "SELECT id FROM matches WHERE user_id = :user_id "
                "AND resume_id = :resume_id AND job_id = :job_id "
                "ORDER BY created_at, id LIMIT 1"
            ),
            {
                "user_id": version["user_id"],
                "resume_id": version["base_resume_id"],
                "job_id": version["job_id"],
            },
        ).scalar_one_or_none()
        if match_id:
            bind.execute(
                sa.text(
                    "UPDATE resume_versions SET match_id = :match_id WHERE id = :version_id"
                ),
                {"match_id": match_id, "version_id": version["id"]},
            )


def _correct_negative_ledger_balances() -> None:
    """Keep the immutable ledger and materialized balance mathematically equal."""
    bind = op.get_bind()
    negative = list(
        bind.execute(
            sa.text(
                "SELECT user_id, quota_type, SUM(delta) AS balance "
                "FROM quota_ledger GROUP BY user_id, quota_type HAVING SUM(delta) < 0"
            )
        ).mappings()
    )
    for row in negative:
        quota_type = str(row["quota_type"])
        correction_key = (
            "migration:0007:negative-balance-correction:"
            + uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"ai-job-coach:0007:{row['user_id']}:{quota_type}",
            ).hex
        )
        candidate_key = correction_key
        suffix = 0
        while bind.execute(
            sa.text(
                "SELECT 1 FROM quota_ledger WHERE user_id = :user_id "
                "AND quota_type = :quota_type AND idempotency_key = :idempotency_key"
            ),
            {
                "user_id": row["user_id"],
                "quota_type": quota_type,
                "idempotency_key": candidate_key,
            },
        ).first():
            suffix += 1
            candidate_key = f"{correction_key}:{suffix}"
        bind.execute(
            sa.text(
                "INSERT INTO quota_ledger "
                "(id, user_id, order_id, quota_type, delta, reason, reference_type, "
                "reference_id, expires_at, idempotency_key, request_hash, created_at) "
                "VALUES (:id, :user_id, NULL, :quota_type, :delta, :reason, "
                ":reference_type, '', NULL, :idempotency_key, :request_hash, "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid.uuid4()),
                "user_id": row["user_id"],
                "quota_type": row["quota_type"],
                "delta": -int(row["balance"]),
                "reason": "0007 迁移补正历史负余额",
                "reference_type": "migration_correction",
                "idempotency_key": candidate_key,
                "request_hash": candidate_key[-64:],
            },
        )


def upgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    with _sqlite_rebuild_window():
        ledger_columns = {
            column["name"] for column in inspect(bind).get_columns("quota_ledger")
        }
        if "request_hash" not in ledger_columns:
            op.add_column(
                "quota_ledger",
                sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
            )
        _correct_negative_ledger_balances()

        if "quota_balances" not in tables:
            op.create_table(
                "quota_balances",
                sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
                sa.Column("quota_type", sa.String(30), primary_key=True),
                sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                sa.CheckConstraint("balance >= 0", name="ck_quota_balances_nonnegative"),
            )
            bind.execute(
                sa.text(
                    "INSERT INTO quota_balances (user_id, quota_type, balance, updated_at) "
                    "SELECT user_id, quota_type, COALESCE(SUM(delta), 0), CURRENT_TIMESTAMP "
                    "FROM quota_ledger GROUP BY user_id, quota_type"
                )
            )

        _deduplicate_matches()
        if "uq_matches_user_resume_job" not in _unique_names("matches"):
            with op.batch_alter_table("matches") as batch:
                batch.create_unique_constraint(
                    "uq_matches_user_resume_job",
                    ["user_id", "resume_id", "job_id"],
                )

        version_columns = {
            column["name"] for column in inspect(bind).get_columns("resume_versions")
        }
        if "match_id" not in version_columns:
            with op.batch_alter_table("resume_versions") as batch:
                batch.add_column(sa.Column("match_id", sa.String(36), nullable=True))
                batch.create_foreign_key(
                    "fk_resume_versions_match_id",
                    "matches",
                    ["match_id"],
                    ["id"],
                )
                batch.create_index("ix_resume_versions_match_id", ["match_id"])
        _backfill_resume_version_matches()

        if "application_channels" in tables and (
            "uq_application_channel_identity" in _unique_names("application_channels")
            or "ix_application_channels_content_hash"
            in _index_names("application_channels")
        ):
            with op.batch_alter_table("application_channels") as batch:
                if "uq_application_channel_identity" in _unique_names(
                    "application_channels"
                ):
                    batch.drop_constraint(
                        "uq_application_channel_identity", type_="unique"
                    )
                if "ix_application_channels_content_hash" in _index_names(
                    "application_channels"
                ):
                    batch.drop_index("ix_application_channels_content_hash")

        current_tables = set(inspect(bind).get_table_names())
        if "quota_reservations" not in current_tables:
            op.create_table(
                "quota_reservations",
                sa.Column(
                    "ledger_id",
                    sa.String(36),
                    sa.ForeignKey("quota_ledger.id", ondelete="CASCADE"),
                    primary_key=True,
                ),
                sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("quota_type", sa.String(30), nullable=False),
                sa.Column("amount", sa.Integer(), nullable=False),
                sa.Column("resource_type", sa.String(50), nullable=False),
                sa.Column("resource_id", sa.String(100), nullable=False),
                sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                ),
            )
            op.create_index(
                "ix_quota_reservations_user_id",
                "quota_reservations",
                ["user_id"],
            )
            op.create_index(
                "ix_quota_reservations_status",
                "quota_reservations",
                ["status"],
            )
        else:
            if "ix_quota_reservations_user_id" not in _index_names(
                "quota_reservations"
            ):
                op.create_index(
                    "ix_quota_reservations_user_id",
                    "quota_reservations",
                    ["user_id"],
                )
            if "ix_quota_reservations_status" not in _index_names(
                "quota_reservations"
            ):
                op.create_index(
                    "ix_quota_reservations_status",
                    "quota_reservations",
                    ["status"],
                )

        if "capability_target_runs" not in current_tables:
            op.create_table(
                "capability_target_runs",
                sa.Column(
                    "match_id",
                    sa.String(36),
                    sa.ForeignKey("matches.id", ondelete="CASCADE"),
                    primary_key=True,
                ),
                sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
                sa.Column("claim_token", sa.String(36), nullable=False),
                sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
                sa.Column("provider", sa.String(50), nullable=False, server_default=""),
                sa.Column("last_error", sa.String(200), nullable=False, server_default=""),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                ),
            )
            op.create_index(
                "ix_capability_target_runs_user_id",
                "capability_target_runs",
                ["user_id"],
            )
        elif "ix_capability_target_runs_user_id" not in _index_names(
            "capability_target_runs"
        ):
            op.create_index(
                "ix_capability_target_runs_user_id",
                "capability_target_runs",
                ["user_id"],
            )

        if "application_channel_reports" not in current_tables:
            op.create_table(
                "application_channel_reports",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column(
                    "channel_id",
                    sa.String(36),
                    sa.ForeignKey("application_channels.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "user_id",
                    sa.String(36),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                ),
                sa.UniqueConstraint(
                    "channel_id",
                    "user_id",
                    name="uq_application_channel_reports_channel_user",
                ),
            )
            op.create_index(
                "ix_application_channel_reports_channel_id",
                "application_channel_reports",
                ["channel_id"],
            )
            op.create_index(
                "ix_application_channel_reports_user_id",
                "application_channel_reports",
                ["user_id"],
            )
        else:
            if "ix_application_channel_reports_channel_id" not in _index_names(
                "application_channel_reports"
            ):
                op.create_index(
                    "ix_application_channel_reports_channel_id",
                    "application_channel_reports",
                    ["channel_id"],
                )
            if "ix_application_channel_reports_user_id" not in _index_names(
                "application_channel_reports"
            ):
                op.create_index(
                    "ix_application_channel_reports_user_id",
                    "application_channel_reports",
                    ["user_id"],
                )

        if "storage_deletion_tasks" not in current_tables:
            op.create_table(
                "storage_deletion_tasks",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("file_key", sa.String(255), nullable=False),
                sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("last_error", sa.String(200), nullable=False, server_default=""),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                ),
                sa.Column(
                    "last_attempt_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                ),
                sa.UniqueConstraint(
                    "file_key",
                    name="uq_storage_deletion_tasks_file_key",
                ),
            )


def downgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "application_channels" in tables and (
        "uq_application_channel_identity" not in _unique_names("application_channels")
    ):
        collision = bind.execute(
            sa.text(
                "SELECT 1 FROM application_channels GROUP BY "
                "company_name_normalized, channel_type, url, email HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if collision:
            raise RuntimeError(
                "Cannot downgrade 0007: owner-scoped application channels collide "
                "under the legacy global identity constraint."
            )

    with _sqlite_rebuild_window():
        for table_name in (
            "storage_deletion_tasks",
            "application_channel_reports",
            "capability_target_runs",
            "quota_reservations",
        ):
            if table_name in tables:
                op.drop_table(table_name)

        if "application_channels" in tables and (
            "uq_application_channel_identity" not in _unique_names("application_channels")
            or "ix_application_channels_content_hash"
            not in _index_names("application_channels")
        ):
            with op.batch_alter_table("application_channels") as batch:
                if "uq_application_channel_identity" not in _unique_names(
                    "application_channels"
                ):
                    batch.create_unique_constraint(
                        "uq_application_channel_identity",
                        ["company_name_normalized", "channel_type", "url", "email"],
                    )
                if "ix_application_channels_content_hash" not in _index_names(
                    "application_channels"
                ):
                    batch.create_index(
                        "ix_application_channels_content_hash",
                        ["content_hash"],
                    )

        version_columns = {
            column["name"] for column in inspect(bind).get_columns("resume_versions")
        }
        if "match_id" in version_columns:
            with op.batch_alter_table("resume_versions") as batch:
                batch.drop_index("ix_resume_versions_match_id")
                batch.drop_constraint("fk_resume_versions_match_id", type_="foreignkey")
                batch.drop_column("match_id")

        if "uq_matches_user_resume_job" in _unique_names("matches"):
            with op.batch_alter_table("matches") as batch:
                batch.drop_constraint("uq_matches_user_resume_job", type_="unique")

        if "quota_balances" in tables:
            op.drop_table("quota_balances")
        ledger_columns = {
            column["name"] for column in inspect(bind).get_columns("quota_ledger")
        }
        if "request_hash" in ledger_columns:
            with op.batch_alter_table("quota_ledger") as batch:
                batch.drop_column("request_hash")
