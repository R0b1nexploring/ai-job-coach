"""Add the unified task table and backfill existing bundle runs.

Creates ``tasks`` as the shared persistent execution record, backfills every
existing ``resume_bundle_runs`` row through the canonical status mapping, and
leaves ``resume_bundle_runs`` as the current claim owner. No column is dropped
and no legacy row is rewritten, so an older application image keeps working
against the migrated database.
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0012_add_unified_tasks"
down_revision = "0011_add_persistent_resume_task_fields"
branch_labels = None
depends_on = None


# Stored legacy bundle status -> unified task status. Kept in the migration on
# purpose: the backfill must not follow a future code change in
# app.services.task_status.
BUNDLE_TO_TASK = {
    "queued": "queued",
    "generating": "running",
    "ready": "succeeded",
    "degraded": "degraded",
    "failed": "failed",
}

TASK_STATUSES = ("queued", "running", "succeeded", "degraded", "failed")


def _index_names(table: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "tasks" not in tables:
        op.create_table(
            "tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("task_type", sa.String(40), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("phase", sa.String(40), nullable=False, server_default="queued"),
            sa.Column("resource_ids_json", sa.JSON(), nullable=False),
            sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("result_resources_json", sa.JSON(), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("idempotency_key", sa.String(200), nullable=False),
            sa.Column("parent_task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=True),
            sa.Column("retry_of_task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=True),
            sa.Column("guide_version_id", sa.String(36), nullable=True),
            sa.Column("guide_content_hash", sa.String(64), nullable=True),
            sa.Column("guide_kind", sa.String(20), nullable=True),
            sa.Column("claim_token", sa.String(36), nullable=False, server_default=""),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("public_error_code", sa.String(60), nullable=False, server_default=""),
            sa.Column("internal_error_code", sa.String(60), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "user_id",
                "idempotency_key",
                name="uq_tasks_user_idempotency",
            ),
            sa.UniqueConstraint(
                "user_id",
                "guide_version_id",
                "guide_content_hash",
                "guide_kind",
                name="uq_tasks_auto_guide",
            ),
            sa.CheckConstraint(
                "status IN ('queued','running','succeeded','degraded','failed')",
                name="ck_tasks_status",
            ),
            sa.CheckConstraint(
                "attempts >= 0 AND max_attempts >= 1",
                name="ck_tasks_attempts",
            ),
        )
        op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
        op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
        op.create_index("ix_tasks_retry_of_task_id", "tasks", ["retry_of_task_id"])
        op.create_index(
            "ix_tasks_queue",
            "tasks",
            ["task_type", "status", "available_at", "created_at"],
        )
        op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"])

    _backfill_bundle_runs(bind)


def _backfill_bundle_runs(bind) -> None:
    """Mirror existing bundle runs into the unified task table once.

    The legacy run keeps its own claim token and attempt counter. This is a
    projection for compatibility, not a second claim owner: the task row copies
    the run's current lease so a scheduled task cannot be handed out twice.
    """
    tables = set(inspect(bind).get_table_names())
    if "resume_bundle_runs" not in tables:
        return
    run_columns = {
        column["name"] for column in inspect(bind).get_columns("resume_bundle_runs")
    }
    required = {"bundle_id", "user_id", "status", "claim_token", "request_hash"}
    if not required <= run_columns:
        return

    optional = {
        "phase": "phase",
        "attempts": "attempts",
        "max_attempts": "max_attempts",
        "input_snapshot_json": "input_snapshot_json",
        "result_resources_json": "result_resources_json",
        "public_error_code": "public_error_code",
        "last_error": "last_error",
        "lease_expires_at": "lease_expires_at",
        "heartbeat_at": "heartbeat_at",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    present_optional = {
        source: target for source, target in optional.items() if source in run_columns
    }

    rows = bind.execute(
        sa.text(
            "SELECT "
            + ", ".join(["bundle_id", "user_id", "status", "claim_token", "request_hash"]
                        + list(present_optional))
            + " FROM resume_bundle_runs"
        )
    ).mappings()
    for row in rows:
        legacy_status = str(row["status"] or "").strip().lower()
        task_status = BUNDLE_TO_TASK.get(legacy_status)
        if task_status is None:
            # An unknown legacy value cannot be projected safely. Leave it out
            # rather than inventing a task state that no consumer understands.
            continue
        bundle_id = str(row["bundle_id"])
        task_id = f"task_migrated_{bundle_id}"
        exists = bind.execute(
            sa.text("SELECT 1 FROM tasks WHERE id = :id"), {"id": task_id}
        ).first()
        if exists:
            continue
        phase = str(row.get("phase") or "") or (
            "queued" if task_status == "queued" else task_status
        )
        snapshot = _json_value(row.get("input_snapshot_json"))
        resources = _json_value(row.get("result_resources_json"))
        created_at = row.get("created_at")
        updated_at = row.get("updated_at") or created_at
        bind.execute(
            sa.text(
                "INSERT INTO tasks ("
                "id, user_id, task_type, status, phase, resource_ids_json,"
                " input_snapshot_json, result_resources_json, request_hash,"
                " idempotency_key, claim_token, attempts, max_attempts,"
                " available_at, lease_expires_at, heartbeat_at,"
                " public_error_code, internal_error_code, created_at, updated_at"
                ") VALUES ("
                ":id, :user_id, 'resume_bundle', :status, :phase, :resource_ids,"
                " :snapshot, :resources, :request_hash, :idempotency_key,"
                " :claim_token, :attempts, :max_attempts,"
                " :available_at, :lease_expires_at, :heartbeat_at,"
                " :public_error_code, :internal_error_code, :created_at, :updated_at"
                ")"
            ),
            {
                "id": task_id,
                "user_id": str(row["user_id"]),
                "status": task_status,
                "phase": phase[:40],
                "resource_ids": _dump_json({"bundle_id": bundle_id}),
                "snapshot": _dump_json(snapshot),
                "resources": _dump_json(resources),
                "request_hash": str(row.get("request_hash") or ""),
                # Legacy runs have no idempotency key of their own. Deriving it
                # from the bundle id keeps the backfill re-runnable and avoids
                # colliding two migrated runs for the same user.
                "idempotency_key": f"migration:0012:bundle:{bundle_id}",
                "claim_token": str(row.get("claim_token") or ""),
                "attempts": int(row.get("attempts") or 0),
                "max_attempts": int(row.get("max_attempts") or 3),
                "available_at": row.get("lease_expires_at"),
                "lease_expires_at": row.get("lease_expires_at"),
                "heartbeat_at": row.get("heartbeat_at"),
                "public_error_code": str(row.get("public_error_code") or "")[:60],
                "internal_error_code": str(row.get("last_error") or "")[:60],
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )


def _json_value(value):
    if value is None or isinstance(value, (dict, list)):
        return value if value is not None else {}
    import json

    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _dump_json(value) -> str:
    import json

    return json.dumps(value if isinstance(value, (dict, list)) else {}, ensure_ascii=False)


def downgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "tasks" not in tables:
        return
    for name in (
        "ix_tasks_user_status",
        "ix_tasks_queue",
        "ix_tasks_retry_of_task_id",
        "ix_tasks_parent_task_id",
        "ix_tasks_user_id",
    ):
        if name in _index_names("tasks"):
            op.drop_index(name, table_name="tasks")
    op.drop_table("tasks")
