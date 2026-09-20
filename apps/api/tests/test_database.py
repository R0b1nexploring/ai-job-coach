import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import normalize_database_url
from app.database import make_engine


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgresql://coach:pw@db.example/coach", "postgresql+psycopg://coach:pw@db.example/coach"),
        ("postgres://coach:pw@db.example/coach", "postgresql+psycopg://coach:pw@db.example/coach"),
        ("postgresql+psycopg://coach@db.example/coach", "postgresql+psycopg://coach@db.example/coach"),
        ("sqlite:///./var/app.db", "sqlite:///./var/app.db"),
    ],
)
def test_database_url_normalization(raw, expected):
    assert normalize_database_url(raw) == expected


def test_postgresql_engine_uses_psycopg_driver():
    engine = make_engine("postgresql://coach:coach@db.example/coach")
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_sqlite_foreign_keys_are_enabled_for_every_connection(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'foreign-keys.db'}")

    with engine.begin() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA busy_timeout")) == 30_000
        connection.execute(text("CREATE TABLE parents (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE children ("
                "id INTEGER PRIMARY KEY, "
                "parent_id INTEGER NOT NULL REFERENCES parents(id)"
                ")"
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("INSERT INTO children (id, parent_id) VALUES (1, 999)"))

    engine.dispose()
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA busy_timeout")) == 30_000

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("INSERT INTO children (id, parent_id) VALUES (2, 999)"))

    engine.dispose()
