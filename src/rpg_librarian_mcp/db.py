from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlmodel import Session, create_engine

from .catalog import Catalog


def _run_alembic_upgrade(db_path: Path) -> None:
    alembic_dir = resources.files("rpg_librarian_mcp") / "alembic"
    with resources.as_file(alembic_dir) as alembic_path:
        cfg = Config(str(alembic_path / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(cfg, "head")


def _setup_db(db_path: Path) -> None:
    _run_alembic_upgrade(db_path)


def ensure_bootstrapped(catalog: Catalog) -> None:
    if not catalog.catalog_dir.exists():
        catalog.catalog_dir.mkdir(parents=True)
    if not catalog.db_path.exists():
        _setup_db(catalog.db_path)


def migrate_existing(catalog: Catalog) -> None:
    """Explicit upgrade path for an existing catalog after a schema-changing release."""
    if not catalog.db_path.exists():
        raise RuntimeError(
            f"No catalog found at {catalog.db_path} -- nothing to migrate. "
            "Run the server once first to create a new catalog."
        )
    _run_alembic_upgrade(catalog.db_path)


@contextmanager
def session_scope(catalog: Catalog) -> Generator[Session]:
    ensure_bootstrapped(catalog)
    engine = create_engine(f"sqlite:///{catalog.db_path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
