from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from clipscore.config import get_settings
from clipscore.db.base import Base
from clipscore.db import models  # noqa: F401 — register tables

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().db_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)  # batch mode: SQLite ALTER support
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
