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
