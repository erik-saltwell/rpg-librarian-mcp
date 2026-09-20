from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

from .errors import CatalogNotFoundError


def upgrade(db_path: Path) -> None:
    """Create the catalog if needed and migrate it to the current schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    alembic_dir = resources.files("rpg_librarian") / "alembic"
    with resources.as_file(alembic_dir) as alembic_path:
        cfg = Config(str(alembic_path / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        cfg.attributes["configure_logger"] = False
        command.upgrade(cfg, "head")


def create_catalog_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


@contextmanager
def session_scope(db_path: Path, *, migrate: bool = True) -> Generator[Session]:
    """A session on an existing catalog, migrated to head unless `migrate` is False.

    Commits when the block exits cleanly and rolls back if it raises, so one block is
    one transaction. Never creates the catalog; only `init` does. A long-running
    server migrates once at startup and passes `migrate=False` per call.
    """
    if not db_path.exists():
        raise CatalogNotFoundError(db_path)
    if migrate:
        upgrade(db_path)
    engine = create_catalog_engine(db_path)
    try:
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
    finally:
        engine.dispose()


@contextmanager
def readonly_connection(db_path: Path) -> Generator[sqlite3.Connection]:
    """A connection that SQLite itself refuses to write through."""
    if not db_path.exists():
        raise CatalogNotFoundError(db_path)
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        yield connection
    finally:
        connection.close()
