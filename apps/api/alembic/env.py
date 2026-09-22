from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.database import Base
from app.models import entities  # noqa: F401


config = context.config
config.set_main_option("sqlalchemy.url", get_settings().resolved_database_url())
if config.config_file_name:
    # Alembic runs in-process in migration tests and maintenance commands.
    # Keep application loggers alive instead of globally disabling every logger
    # omitted from alembic.ini.
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata

# Alembic 1.14+ creates ``alembic_version.version_num`` as VARCHAR(32), but this
# project's revision ids are longer (up to 44 characters, e.g.
# ``0010_add_resume_bundles_and_interview_guides``). On PostgreSQL that makes a
# fresh ``alembic upgrade head`` fail with a string-truncation error once the
# chain reaches a long revision. Databases created by an older Alembic already
# have a wider column, so only a missing table needs the explicit width.
VERSION_TABLE = "alembic_version"
VERSION_NUM_LENGTH = 128


def _ensure_version_table(connection) -> None:
    """Create the version table with a width that fits our revision ids.

    Alembic only creates this table when it is absent, so widening it here
    leaves existing databases untouched.
    """
    from sqlalchemy import inspect

    if VERSION_TABLE in inspect(connection).get_table_names():
        return
    connection.exec_driver_sql(
        f"CREATE TABLE {VERSION_TABLE} ("
        f"version_num VARCHAR({VERSION_NUM_LENGTH}) NOT NULL, "
        f"CONSTRAINT {VERSION_TABLE}_pkc PRIMARY KEY (version_num)"
        ")"
    )


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    from app.database import make_engine

    url = config.get_main_option("sqlalchemy.url")
    is_sqlite = url.startswith("sqlite")
    with make_engine(url).connect() as connection:
        _ensure_version_table(connection)
        # Commit the widened table before Alembic starts managing the
        # transaction. Alembic treats an already-open transaction as its own and
        # would otherwise roll this DDL back with the migration batch.
        connection.commit()
        if is_sqlite:
            # SQLite cannot add a foreign key without rebuilding the table, and
            # a rebuild drops the table. With child rows present (for example
            # resume_versions.bundle_id -> resume_bundles) FK enforcement makes
            # that drop fail. Disable it for the migration window and restore it
            # afterwards; the batch copy still preserves the existing rows.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
