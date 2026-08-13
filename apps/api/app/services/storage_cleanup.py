import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import StorageDeletionTask
from app.providers.storage.base import StorageProvider


def normalized_file_key(file_key: str) -> str:
    """Store only provider keys, never caller-supplied paths."""
    return Path(file_key).name.strip()


def enqueue_file_deletions(db: Session, file_keys: Iterable[str]) -> list[str]:
    """Persist deletion locators in the caller's transaction."""
    scheduled: list[str] = []
    keys = [
        key
        for key in dict.fromkeys(normalized_file_key(key) for key in file_keys)
        if key
    ]
    if not keys:
        return []
    dialect_name = db.get_bind().dialect.name
    for file_key in keys:
        values = {"id": str(uuid.uuid4()), "file_key": file_key}
        if dialect_name == "sqlite":
            statement = sqlite_insert(StorageDeletionTask).values(**values).on_conflict_do_nothing(
                index_elements=["file_key"]
            )
        elif dialect_name == "postgresql":
            statement = postgresql_insert(StorageDeletionTask).values(
                **values
            ).on_conflict_do_nothing(index_elements=["file_key"])
        else:
            existing = db.scalar(
                select(StorageDeletionTask.id).where(StorageDeletionTask.file_key == file_key)
            )
            if existing is None:
                db.add(StorageDeletionTask(**values))
            scheduled.append(file_key)
            continue
        db.execute(statement)
        scheduled.append(file_key)
    return scheduled


def process_storage_deletions(
    db: Session,
    storage: StorageProvider,
    *,
    file_keys: Iterable[str] | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """Best-effort deletion that retains every failed locator for a later retry."""
    statement = select(StorageDeletionTask).order_by(StorageDeletionTask.created_at)
    if file_keys is not None:
        normalized = list(
            dict.fromkeys(normalized_file_key(key) for key in file_keys if key)
        )
        if not normalized:
            return {"files_removed": 0, "files_delete_failed": 0}
        statement = statement.where(StorageDeletionTask.file_key.in_(normalized))
    tasks = list(db.scalars(statement.limit(max(1, limit))))

    removed = 0
    failed = 0
    for task in tasks:
        try:
            storage.delete(task.file_key)
        except Exception as exc:
            task.attempts += 1
            task.last_attempt_at = datetime.now(timezone.utc)
            task.last_error = type(exc).__name__[:200]
            failed += 1
        else:
            db.delete(task)
            removed += 1
    if tasks:
        db.commit()
    return {"files_removed": removed, "files_delete_failed": failed}


def schedule_and_process_file_deletions(
    bind: Engine,
    storage: StorageProvider,
    *,
    file_keys: Iterable[str],
) -> dict[str, int]:
    """Durably schedule orphan cleanup in an isolated transaction, then attempt it.

    This is used after the business transaction has already rolled back. A fresh
    Session keeps cleanup persistence independent from the failed request Session.
    """
    cleanup_session = sessionmaker(bind=bind, expire_on_commit=False)
    with cleanup_session() as db:
        scheduled = enqueue_file_deletions(db, file_keys)
        db.commit()
        return process_storage_deletions(
            db,
            storage,
            file_keys=scheduled,
            limit=max(1, len(scheduled)),
        )
