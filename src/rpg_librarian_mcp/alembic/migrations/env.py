import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from rpg_librarian_mcp import model  # noqa: F401
from rpg_librarian_mcp.catalog import load_env

config = context.config

# alembic.ini's checked-in sqlalchemy.url is a placeholder -- nothing is
# ever meant to migrate against it directly. Its only job is to mark "no
# real target configured yet", so DATABASE_URL (a dev-only override, see
# .env.example) can fill in for it when alembic is invoked directly from
# the CLI with no other target. When db.py calls into alembic
# programmatically for a real server run, it already set sqlalchemy.url to
# the actual library's db_path before this module ever loads -- that real,
# already-configured target must always win over a stray DATABASE_URL left
# in a checkout's .env, or a scratch/dev library sitting under this repo
# would silently receive migrations meant for a different library root.
_UNCONFIGURED_URL = "driver://user:pass@localhost/dbname"

load_env()
if config.get_main_option("sqlalchemy.url") in (None, _UNCONFIGURED_URL):
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
