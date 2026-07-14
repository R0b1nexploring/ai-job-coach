from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.database import Base
from app.models import entities  # noqa: F401


config = context.config
config.set_main_option("sqlalchemy.url", get_settings().resolved_database_url())
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction(): context.run_migrations()


def run_migrations_online():
    from app.database import make_engine
    with make_engine(config.get_main_option("sqlalchemy.url")).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction(): context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()

