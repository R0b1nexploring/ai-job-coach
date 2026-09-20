from collections.abc import AsyncGenerator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings, normalize_database_url


class Base(DeclarativeBase):
    pass


# Tables whose rows can carry or point at user-owned personal data. The check is
# intentionally based on table names so database.py does not import mapped models
# (entities.py itself imports Base from this module).
_OWNER_COLUMNS = {
    "user_profiles": "user_id",
    "advisor_assignments": "user_id",
    "resumes": "user_id",
    "resume_facts": "user_id",
    "jobs": "created_by",
    "matches": "user_id",
    "capability_targets": "user_id",
    "capability_target_runs": "user_id",
    "resume_versions": "user_id",
    "target_profiles": "user_id",
    "resume_bundles": "user_id",
    "resume_bundle_runs": "user_id",
    "interview_guides": "user_id",
    "applications": "user_id",
    "application_channels": "owner_user_id",
    "campus_announcements": "owner_user_id",
    "experience_entries": "owner_user_id",
    "application_channel_reports": "user_id",
    "interviews": "user_id",
    "orders": "user_id",
    "quota_ledger": "user_id",
    "quota_balances": "user_id",
    "quota_reservations": "user_id",
    "notifications": "user_id",
}


def _table_name(value: object) -> str:
    return inspect(value).mapper.local_table.name


@event.listens_for(Session, "before_flush")
def reject_inactive_owner_writes(session: Session, _flush_context, _instances) -> None:
    """Close the auth-check/commit race for writes containing personal data.

    Authentication may have loaded an active User before a concurrent maintenance
    transaction claims or deletes it. Reading through Session.get() here would use
    that stale identity-map object, so statuses are fetched with the transaction's
    connection immediately before SQL is emitted.
    """
    pending = list(session.new)
    changed = [
        value
        for value in session.dirty
        if session.is_modified(value, include_collections=False)
    ]
    if not pending and not changed:
        return

    newly_created_users: set[str] = set()
    purge_owner_ids: set[str] = set(session.info.get("pii_purge_owner_ids", ()))
    for value in [*pending, *changed]:
        if _table_name(value) != "users":
            continue
        user_id = getattr(value, "id", None)
        if not user_id:
            continue
        if value in session.new:
            newly_created_users.add(user_id)

    owner_writes: dict[str, list[object]] = {}
    application_owner_by_id: dict[str, str] = {}
    application_event_ids: set[str] = set()
    for value in [*pending, *changed]:
        table_name = _table_name(value)
        owner_column = _OWNER_COLUMNS.get(table_name)
        if owner_column:
            owner_id = getattr(value, owner_column, None)
            if owner_id:
                owner_writes.setdefault(owner_id, []).append(value)
                if table_name == "applications":
                    application_owner_by_id[value.id] = owner_id
        elif table_name == "application_events":
            application_id = getattr(value, "application_id", None)
            if application_id:
                application_event_ids.add(application_id)
        elif table_name == "users" and value not in session.new:
            user_id = getattr(value, "id", None)
            if user_id and getattr(value, "status", None) != "deleted":
                owner_writes.setdefault(user_id, []).append(value)

    unresolved_application_ids: set[str] = set()
    for application_id in application_event_ids:
        owner_id = application_owner_by_id.get(application_id)
        if owner_id:
            owner_writes.setdefault(owner_id, [])
        else:
            unresolved_application_ids.add(application_id)

    connection = session.connection()
    owner_ids = set(owner_writes) - newly_created_users - purge_owner_ids
    for owner_id in owner_ids:
        # A conditional no-op UPDATE is both the status re-check and the first write
        # lock for this owner. If this request wins, purge waits and subsequently
        # cleans the committed data. If purge wins, rowcount is zero and no PII SQL
        # from this flush can be emitted. This closes the SELECT/check/use gap.
        transition = connection.execute(
            text(
                "UPDATE users SET updated_at = updated_at "
                "WHERE id = :user_id AND status = 'active'"
            ),
            {"user_id": owner_id},
        )
        if transition.rowcount != 1:
            # Import lazily to keep database/model initialization acyclic.
            from .errors import AppError

            raise AppError(
                "ACCOUNT_WRITE_CONFLICT",
                "账号状态已变化，本次写入已取消，请刷新后重试。",
                409,
            )

    for application_id in unresolved_application_ids:
        if purge_owner_ids:
            # Purge has already changed the account out of active state. A read is
            # safe in that explicit scope and lets its event-note anonymization pass.
            event_owner_id = connection.execute(
                text("SELECT user_id FROM applications WHERE id = :application_id"),
                {"application_id": application_id},
            ).scalar_one_or_none()
            if event_owner_id in purge_owner_ids:
                continue
        transition = connection.execute(
            text(
                "UPDATE users SET updated_at = updated_at "
                "WHERE status = 'active' AND id = ("
                "SELECT user_id FROM applications WHERE id = :application_id"
                ")"
            ),
            {"application_id": application_id},
        )
        if transition.rowcount != 1:
            from .errors import AppError

            raise AppError(
                "ACCOUNT_WRITE_CONFLICT",
                "账号状态已变化，本次写入已取消，请刷新后重试。",
                409,
            )


def make_engine(url: str | None = None) -> Engine:
    database_url = normalize_database_url(url or get_settings().resolved_database_url())
    is_sqlite = make_url(database_url).get_backend_name() == "sqlite"
    if is_sqlite:
        database_engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
    else:
        settings = get_settings()
        database_engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
        )

    if is_sqlite:

        @event.listens_for(database_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
            finally:
                cursor.close()

    return database_engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[Session, None]:
    with SessionLocal() as session:
        yield session
