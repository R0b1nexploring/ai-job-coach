from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.config import get_settings
from app.database import Base, make_engine
from app.models import entities  # noqa: F401

API_ROOT = Path(__file__).resolve().parents[1]
INITIAL_TABLES = {
    "advisor_assignments",
    "application_events",
    "applications",
    "audit_logs",
    "interviews",
    "jobs",
    "matches",
    "notifications",
    "orders",
    "packages",
    "quota_ledger",
    "resume_facts",
    "resume_versions",
    "resumes",
    "user_profiles",
    "users",
}
REVISION_CHAIN = (
    ("0001_initial", "base"),
    ("0002_scope_quota_idempotency", "0001_initial"),
    ("0003_add_retention_fields", "0002_scope_quota_idempotency"),
    ("0004_add_capability_targets", "0003_add_retention_fields"),
    ("0005_add_resume_extraction_fields", "0004_add_capability_targets"),
    ("0006_add_application_channels", "0005_add_resume_extraction_fields"),
    ("0007_harden_integrity", "0006_add_application_channels"),
    ("0008_add_experience_and_campus_catalog", "0007_harden_integrity"),
    ("0009_add_target_profiles_and_material_claims", "0008_add_experience_and_campus_catalog"),
    ("0010_add_resume_bundles_and_interview_guides", "0009_add_target_profiles_and_material_claims"),
    ("0011_add_persistent_resume_task_fields", "0010_add_resume_bundles_and_interview_guides"),
    ("0012_add_unified_tasks", "0011_add_persistent_resume_task_fields"),
    ("0013_add_invite_codes", "0012_add_unified_tasks"),
    ("0014_add_bundle_revision_lineage", "0013_add_invite_codes"),
)


@pytest.fixture()
def migration_database(isolated_test_environment, monkeypatch):
    database_path = isolated_test_environment / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    try:
        yield config, database_path
    finally:
        get_settings.cache_clear()


def _schema_snapshot(database_path: Path) -> dict:
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        tables = sorted(set(inspector.get_table_names()) - {"alembic_version"})
        snapshot = {}
        for table in tables:
            snapshot[table] = {
                "columns": tuple(
                    (column["name"], str(column["type"]), column["nullable"])
                    for column in inspector.get_columns(table)
                ),
                "foreign_keys": tuple(
                    sorted(
                        (
                            tuple(foreign_key["constrained_columns"]),
                            foreign_key["referred_table"],
                            tuple(foreign_key["referred_columns"]),
                        )
                        for foreign_key in inspector.get_foreign_keys(table)
                    )
                ),
                "indexes": tuple(
                    sorted(
                        (tuple(index["column_names"]), bool(index["unique"]))
                        for index in inspector.get_indexes(table)
                    )
                ),
                "unique_constraints": tuple(
                    sorted(
                        tuple(constraint["column_names"])
                        for constraint in inspector.get_unique_constraints(table)
                    )
                ),
            }
        return snapshot
    finally:
        engine.dispose()


def _column_names(database_path: Path, table: str) -> set[str]:
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        return {column["name"] for column in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _unique_column_sets(database_path: Path, table: str) -> set[tuple[str, ...]]:
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        return {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints(table)
        }
    finally:
        engine.dispose()


def _assert_revision_effect(revision: str, database_path: Path) -> None:
    snapshot = _schema_snapshot(database_path)
    if revision == "0001_initial":
        assert set(snapshot) == INITIAL_TABLES
        assert "last_active_at" not in _column_names(database_path, "users")
        assert "organization" not in _column_names(database_path, "resume_facts")
        assert "contact_json" not in _column_names(database_path, "resumes")
    elif revision == "0002_scope_quota_idempotency":
        assert _unique_column_sets(database_path, "quota_ledger") == {
            ("user_id", "quota_type", "idempotency_key")
        }
    elif revision == "0003_add_retention_fields":
        assert {
            "last_active_at",
            "deletion_requested_at",
            "retention_expires_at",
        } <= _column_names(database_path, "users")
    elif revision == "0004_add_capability_targets":
        assert "capability_targets" in snapshot
        assert {"organization", "role_title", "provenance"} <= _column_names(
            database_path, "resume_facts"
        )
        assert {"kind", "unachieved_count"} <= _column_names(database_path, "resume_versions")
    elif revision == "0005_add_resume_extraction_fields":
        assert {"contact_json", "missing_information_json"} <= _column_names(
            database_path, "resumes"
        )
    elif revision == "0006_add_application_channels":
        assert "application_channels" in snapshot
        assert "channel_id" in _column_names(database_path, "applications")
    elif revision == "0007_harden_integrity":
        assert {
            "quota_balances",
            "quota_reservations",
            "capability_target_runs",
            "application_channel_reports",
            "storage_deletion_tasks",
        } <= set(snapshot)
        assert "request_hash" in _column_names(database_path, "quota_ledger")
        assert "match_id" in _column_names(database_path, "resume_versions")
        assert ("user_id", "resume_id", "job_id") in _unique_column_sets(database_path, "matches")
    elif revision == "0008_add_experience_and_campus_catalog":
        assert "campus_announcements" in snapshot
        assert "experience_entries" in snapshot
        assert {
            "owner_user_id",
            "channel_id",
            "announcement_id",
            "source_updated_at",
        } <= _column_names(database_path, "jobs")
    elif revision == "0009_add_target_profiles_and_material_claims":
        assert "target_profiles" in snapshot
        assert "target_profile_sources" in snapshot
        assert {
            "details_json",
            "clarifications_json",
            "completeness_score",
            "status",
        } <= _column_names(database_path, "experience_entries")
        assert {"material_id", "claim_type", "evidence_json"} <= _column_names(
            database_path, "resume_facts"
        )
    elif revision == "0010_add_resume_bundles_and_interview_guides":
        assert "resume_bundles" in snapshot
        assert "resume_bundle_runs" in snapshot
        assert "interview_guides" in snapshot
        assert {
            "bundle_id",
            "target_profile_id",
            "quality_report_json",
            "content_hash",
            "template_snapshot_json",
        } <= _column_names(database_path, "resume_versions")
    elif revision == "0011_add_persistent_resume_task_fields":
        assert {
            "task_type",
            "phase",
            "input_snapshot_json",
            "result_resources_json",
            "public_error_code",
            "attempts",
            "retry_count",
            "max_attempts",
            "lease_expires_at",
            "heartbeat_at",
        } <= _column_names(database_path, "resume_bundle_runs")
    elif revision == "0012_add_unified_tasks":
        assert "tasks" in snapshot
        assert {
            "task_type",
            "status",
            "phase",
            "resource_ids_json",
            "input_snapshot_json",
            "result_resources_json",
            "idempotency_key",
            "parent_task_id",
            "retry_of_task_id",
            "guide_version_id",
            "guide_content_hash",
            "guide_kind",
            "claim_token",
            "attempts",
            "max_attempts",
            "available_at",
            "lease_expires_at",
            "heartbeat_at",
            "first_claimed_at",
            "deadline_at",
            "public_error_code",
            "internal_error_code",
        } <= _column_names(database_path, "tasks")
        assert ("user_id", "idempotency_key") in _unique_column_sets(
            database_path, "tasks"
        )
        assert (
            "user_id",
            "guide_version_id",
            "guide_content_hash",
            "guide_kind",
        ) in _unique_column_sets(database_path, "tasks")
    elif revision == "0013_add_invite_codes":
        assert "invite_codes" in snapshot
        assert {
            "code_hash",
            "label",
            "max_uses",
            "used_count",
            "expires_at",
            "revoked_at",
        } <= _column_names(database_path, "invite_codes")
    elif revision == "0014_add_bundle_revision_lineage":
        assert {"parent_bundle_id", "revision_json"} <= _column_names(
            database_path, "resume_bundles"
        )


@pytest.mark.parametrize(("revision", "parent"), REVISION_CHAIN)
def test_each_revision_upgrades_and_downgrades_cleanly(migration_database, revision, parent):
    config, database_path = migration_database
    if parent != "base":
        command.upgrade(config, parent)
    before = _schema_snapshot(database_path)

    command.upgrade(config, revision)
    after = _schema_snapshot(database_path)
    assert after != before
    _assert_revision_effect(revision, database_path)

    command.downgrade(config, parent)
    assert _schema_snapshot(database_path) == before


def test_initial_revision_does_not_import_current_orm_metadata():
    source = (API_ROOT / "alembic" / "versions" / "0001_initial.py").read_text()
    assert "app.database" not in source
    assert "app.models" not in source
    assert "Base.metadata" not in source


def test_head_schema_matches_current_model_columns(migration_database):
    config, database_path = migration_database
    command.upgrade(config, "head")
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
        assert actual_tables == set(Base.metadata.tables)
        for table_name, table in Base.metadata.tables.items():
            actual_columns = {
                column["name"]: column for column in inspector.get_columns(table_name)
            }
            assert set(actual_columns) == {column.name for column in table.columns}
            for column in table.columns:
                assert actual_columns[column.name]["nullable"] == column.nullable
    finally:
        engine.dispose()


def test_head_has_no_pending_model_schema_operations(migration_database):
    config, _database_path = migration_database
    command.upgrade(config, "head")
    command.check(config)


def test_version_table_accepts_the_longest_revision_id(migration_database):
    """A fresh database must store revision ids longer than Alembic's default.

    Alembic 1.14+ creates ``alembic_version.version_num`` as VARCHAR(32), but
    this chain contains ids up to 44 characters. On PostgreSQL the default
    width aborts ``upgrade head`` with a string-truncation error, so the
    environment pre-creates the table with a width that fits.
    """
    config, database_path = migration_database
    command.upgrade(config, "head")

    longest = max(
        len(revision)
        for revision, _parent in REVISION_CHAIN
    )
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        column = next(
            column
            for column in inspect(engine).get_columns("alembic_version")
            if column["name"] == "version_num"
        )
    finally:
        engine.dispose()
    assert longest > 32, "this test is meaningless while revision ids fit VARCHAR(32)"
    assert column["type"].length >= longest


def test_migrated_foreign_keys_are_enforced(migration_database):
    config, database_path = migration_database
    command.upgrade(config, "head")
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                sa.insert(
                    sa.table(
                        "notifications",
                        sa.column("id"),
                        sa.column("user_id"),
                        sa.column("title"),
                        sa.column("body"),
                        sa.column("created_at"),
                    )
                ),
                {
                    "id": "notification-without-user",
                    "user_id": "missing-user",
                    "title": "测试",
                    "body": "测试",
                    "created_at": "2026-08-13 00:00:00",
                },
            )
    finally:
        engine.dispose()


def test_0007_upgrades_populated_sqlite_without_breaking_references(migration_database):
    config, database_path = migration_database
    command.upgrade(config, "0006_add_application_channels")
    engine = make_engine(f"sqlite:///{database_path}")
    now = "2026-08-13 00:00:00"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,email,password_hash,display_name,role,status,timezone,"
                    "created_at,updated_at) VALUES "
                    "('u','u@example.test','x','U','user','active','Asia/Shanghai',"
                    ":now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO resumes "
                    "(id,user_id,original_file_key,original_media_type,display_name,parse_status,"
                    "parsed_text,parser_version,facts_confirmed_at,created_at,updated_at) "
                    "VALUES ('r','u','','','R','parsed','text','1',:now,:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO jobs "
                    "(id,created_by,company_name,title,city,salary_text,published_at,source_type,"
                    "source_url,raw_jd,responsibilities_json,must_have_json,nice_to_have_json,"
                    "keywords_json,work_conditions_json,content_hash,status,created_at,updated_at) "
                    "VALUES ('j','u','C','T','','',:now,'manual','','JD','[]','[]','[]','[]','[]',"
                    "'hash','active',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO matches "
                    "(id,user_id,resume_id,job_id,scoring_version,total_score,recommendation,"
                    "dimension_scores_json,evidence_json,gaps_json,confirmations_json,"
                    "ai_explanation_json,created_at) VALUES "
                    "('m','u','r','j','1',1,'x','{}','[]','[]','[]','{}',:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO capability_targets "
                    "(id,user_id,job_id,match_id,requirement,"
                    "acceptance_criteria_json,created_at,updated_at) "
                    "VALUES ('t','u','j','m','req','[]',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO resume_versions "
                    "(id,user_id,base_resume_id,job_id,title,content_json,traceability_json,"
                    "guard_status,review_status,export_file_key,created_at,updated_at) "
                    "VALUES ('v','u','r','j','V','{}','{}','passed','approved','',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO application_channels "
                    "(id,company_name,company_name_normalized,company_aliases_json,channel_type,"
                    "url,email,regions_json,industries_json,content_hash,created_at,updated_at) "
                    "VALUES ('c','C','c','[]','career_page','https://example.com','','[]','[]',"
                    "'channel-hash',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO applications "
                    "(id,user_id,job_id,resume_version_id,status,source_url,notes,"
                    "created_at,updated_at,channel_id) "
                    "VALUES ('a','u','j','v','pending_confirmation','','',:now,:now,'c')"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO quota_ledger "
                    "(id,user_id,quota_type,delta,reason,reference_type,reference_id,"
                    "idempotency_key,created_at) VALUES "
                    "('q','u','resume',-1,'historic race','','','historic-negative',:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO quota_ledger "
                    "(id,user_id,quota_type,delta,reason,reference_type,reference_id,"
                    "idempotency_key,created_at) VALUES "
                    "('q-collision','u','resume',0,'unrelated legacy row','','',"
                    "'migration:0007:negative-balance-correction',:now)"
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert connection.scalar(
                text("SELECT match_id FROM resume_versions WHERE id='v'")
            ) == "m"
            assert connection.scalar(
                text("SELECT match_id FROM capability_targets WHERE id='t'")
            ) == "m"
            assert connection.execute(
                text("SELECT resume_version_id, channel_id FROM applications WHERE id='a'")
            ).one() == ("v", "c")
            assert connection.scalar(
                text(
                    "SELECT SUM(delta) FROM quota_ledger "
                    "WHERE user_id='u' AND quota_type='resume'"
                )
            ) == 0
            assert connection.scalar(
                text("SELECT balance FROM quota_balances WHERE user_id='u' AND quota_type='resume'")
            ) == 0
    finally:
        engine.dispose()


def test_0007_downgrade_refuses_owner_identity_collision_without_partial_schema_loss(
    migration_database,
):
    config, database_path = migration_database
    command.upgrade(config, "head")
    engine = make_engine(f"sqlite:///{database_path}")
    now = "2026-08-13 00:00:00"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,email,password_hash,display_name,role,status,timezone,"
                    "created_at,updated_at) VALUES "
                    "('u','u@example.test','x','U','user','active','Asia/Shanghai',"
                    ":now,:now)"
                ),
                {"now": now},
            )
            for channel_id, owner_id, content_hash in (
                ("global", None, "global-hash"),
                ("private", "u", "private-hash"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO application_channels "
                        "(id,owner_user_id,company_name,company_name_normalized,"
                        "company_aliases_json,channel_type,url,email,scope,regions_json,"
                        "industries_json,source,verify_status,dead_reports,content_hash,notes,"
                        "created_at,updated_at) VALUES "
                        "(:id,:owner,'示例公司','示例公司','[]','website',"
                        "'https://example.test/apply','','both','[]','[]','test','verified',0,"
                        ":content_hash,'',:now,:now)"
                    ),
                    {
                        "id": channel_id,
                        "owner": owner_id,
                        "content_hash": content_hash,
                        "now": now,
                    },
                )

        with pytest.raises(RuntimeError, match="owner-scoped application channels collide"):
            command.downgrade(config, "0006_add_application_channels")

        assert {
            "storage_deletion_tasks",
            "application_channel_reports",
            "capability_target_runs",
            "quota_reservations",
        } <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0007_harden_integrity"
            )
    finally:
        engine.dispose()


def test_0012_backfills_bundle_runs_into_unified_tasks_without_touching_legacy_rows(
    migration_database,
):
    """The migration projects existing runs; it must not rewrite or drop them."""
    config, database_path = migration_database
    command.upgrade(config, "0011_add_persistent_resume_task_fields")
    engine = make_engine(f"sqlite:///{database_path}")
    now = "2026-09-18 10:00:00"
    runs = (
        ("b-queued", "queued", "tok-1", 0, ""),
        ("b-generating", "generating", "tok-2", 2, ""),
        ("b-ready", "ready", "tok-3", 1, ""),
        ("b-degraded", "degraded", "tok-4", 1, ""),
        ("b-failed", "failed", "tok-5", 3, "hard_gates_failed"),
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,email,password_hash,display_name,role,status,timezone,"
                    "created_at,updated_at) VALUES "
                    "('u','u@example.test','x','U','user','active','Asia/Shanghai',"
                    ":now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO resumes "
                    "(id,user_id,original_file_key,original_media_type,display_name,"
                    "parse_status,parsed_text,parser_version,facts_confirmed_at,"
                    "created_at,updated_at) "
                    "VALUES ('r','u','','','R','parsed','t','1',:now,:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO target_profiles "
                    "(id,user_id,mode,title,snapshot_json,input_hash,"
                    "quality_metadata_json,version,created_at,updated_at) "
                    "VALUES ('tp','u','single_jd','T','{}','ih','{}',1,:now,:now)"
                ),
                {"now": now},
            )
            for bundle_id, status, token, attempts, last_error in runs:
                connection.execute(
                    text(
                        "INSERT INTO resume_bundles "
                        "(id,user_id,base_resume_id,target_profile_id,status,"
                        "facts_snapshot_json,target_snapshot_json,template_snapshot_json,"
                        "request_hash,idempotency_key,generation_metadata_json,"
                        "portrait_file_key,created_at,updated_at) "
                        "VALUES (:id,'u','r','tp',:status,'{}','{}','{}','rh',:key,"
                        "'{}','',:now,:now)"
                    ),
                    {
                        "id": bundle_id,
                        "status": status,
                        "key": f"key-{bundle_id}",
                        "now": now,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO resume_bundle_runs "
                        "(bundle_id,user_id,status,task_type,phase,claim_token,"
                        "request_hash,input_snapshot_json,result_resources_json,"
                        "provider,last_error,public_error_code,attempts,retry_count,"
                        "max_attempts,lease_expires_at,heartbeat_at,created_at,updated_at) "
                        "VALUES (:id,'u',:status,'resume_generation','writing',:token,"
                        "'rh','{\"facts\": []}','{}','compatible',:last_error,'',"
                        ":attempts,0,3,NULL,NULL,:now,:now)"
                    ),
                    {
                        "id": bundle_id,
                        "status": status,
                        "token": token,
                        "attempts": attempts,
                        "last_error": last_error,
                        "now": now,
                    },
                )
    finally:
        engine.dispose()

    command.upgrade(config, "0012_add_unified_tasks")
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            migrated = {
                row[0]: row[1]
                for row in connection.execute(
                    text("SELECT id, status FROM tasks ORDER BY id")
                )
            }
            assert migrated == {
                "task_migrated_b-degraded": "degraded",
                "task_migrated_b-failed": "failed",
                "task_migrated_b-generating": "running",
                "task_migrated_b-queued": "queued",
                "task_migrated_b-ready": "succeeded",
            }
            # The legacy rows keep their own status, claim token and attempts.
            assert connection.scalar(
                text("SELECT COUNT(*) FROM resume_bundle_runs")
            ) == len(runs)
            assert sorted(
                row[0]
                for row in connection.execute(
                    text("SELECT status FROM resume_bundle_runs")
                )
            ) == sorted(status for _id, status, _t, _a, _e in runs)
            assert connection.scalar(
                text("SELECT claim_token FROM resume_bundle_runs WHERE bundle_id='b-generating'")
            ) == "tok-2"
            assert connection.scalar(
                text("SELECT attempts FROM resume_bundle_runs WHERE bundle_id='b-failed'")
            ) == 3
            # A claim token is copied so a migrated task cannot be double-claimed.
            assert connection.scalar(
                text("SELECT claim_token FROM tasks WHERE id='task_migrated_b-generating'")
            ) == "tok-2"
            assert connection.scalar(
                text(
                    "SELECT internal_error_code FROM tasks "
                    "WHERE id='task_migrated_b-failed'"
                )
            ) == "hard_gates_failed"
    finally:
        engine.dispose()


def test_0012_backfill_is_idempotent_when_reapplied(migration_database):
    config, database_path = migration_database
    command.upgrade(config, "0012_add_unified_tasks")
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,email,password_hash,display_name,role,status,timezone,"
                    "created_at,updated_at) VALUES "
                    "('u','u@example.test','x','U','user','active','Asia/Shanghai',"
                    ":now,:now)"
                ),
                {"now": "2026-09-18 10:00:00"},
            )
    finally:
        engine.dispose()

    # Re-running the same revision must not duplicate or fail. No bundle run
    # exists here, so the backfill is a no-op in both directions.
    command.downgrade(config, "0011_add_persistent_resume_task_fields")
    command.upgrade(config, "0012_add_unified_tasks")
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM tasks")) == 0
    finally:
        engine.dispose()


def test_0014_upgrades_populated_sqlite_with_child_bundle_rows(migration_database):
    """An existing DB with bundle children must upgrade without losing rows."""
    config, database_path = migration_database
    command.upgrade(config, "0013_add_invite_codes")
    engine = make_engine(f"sqlite:///{database_path}")
    now = "2026-09-22 00:00:00"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,display_name,role,status,"
                    "timezone,created_at,updated_at) VALUES "
                    "('u1','u1@example.test','x','U','user','active','Asia/Shanghai',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO resumes (id,user_id,original_file_key,original_media_type,"
                    "display_name,parse_status,parsed_text,parser_version,created_at,updated_at) "
                    "VALUES ('r1','u1','k','application/pdf','r','parsed','t','1',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO target_profiles (id,user_id,mode,snapshot_json,input_hash,"
                    "quality_metadata_json,created_at,updated_at) VALUES "
                    "('p1','u1','single_jd','{}','h','{}',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO resume_bundles (id,user_id,base_resume_id,target_profile_id,"
                    "facts_snapshot_json,target_snapshot_json,template_snapshot_json,"
                    "idempotency_key,generation_metadata_json,created_at,updated_at) VALUES "
                    "('b1','u1','r1','p1','{}','{}','{}','k','{}',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO resume_versions (id,user_id,base_resume_id,title,kind,"
                    "content_json,traceability_json,guard_status,review_status,export_file_key,"
                    "content_hash,template_snapshot_json,quality_report_json,created_at,updated_at,"
                    "bundle_id) VALUES "
                    "('v1','u1','r1','t','submittable','{}','{}','passed','draft','','h','{}','{}',"
                    ":now,:now,'b1')"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO interview_guides (id,user_id,resume_version_id,target_profile_id,"
                    "kind,content_json,quality_report_json,created_at,updated_at) VALUES "
                    "('g1','u1','v1','p1','submittable','{}','{}',:now,:now)"
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = make_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            assert {"parent_bundle_id", "revision_json"} <= _column_names(
                database_path, "resume_bundles"
            )
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert connection.scalar(text("SELECT COUNT(*) FROM resume_versions WHERE id='v1'")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM interview_guides WHERE id='g1'")) == 1
            assert connection.scalar(text("SELECT bundle_id FROM resume_versions WHERE id='v1'")) == "b1"
    finally:
        engine.dispose()
