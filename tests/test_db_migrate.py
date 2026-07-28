from importlib import resources

import pytest
from alembic import command
from alembic.config import Config

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import migrate_existing


def _catalog(tmp_path):
    catalog = Catalog(library_root=tmp_path)
    catalog.catalog_dir.mkdir(parents=True)
    return catalog


def _stamp_at_revision(db_path, revision: str) -> None:
    alembic_dir = resources.files("rpg_librarian_mcp") / "alembic"
    with resources.as_file(alembic_dir) as alembic_path:
        cfg = Config(str(alembic_path / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(cfg, revision)


def _current_revision(db_path) -> str:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select version_num from alembic_version").fetchone()
        return row[0]
    finally:
        conn.close()


def test_migrate_existing_raises_when_catalog_missing(tmp_path):
    catalog = _catalog(tmp_path)

    with pytest.raises(RuntimeError):
        migrate_existing(catalog)


def _head_revision(tmp_path) -> str:
    reference_db_path = tmp_path / "reference.db"
    _stamp_at_revision(reference_db_path, "head")
    return _current_revision(reference_db_path)


def test_migrate_existing_is_noop_when_already_at_head(tmp_path):
    catalog = _catalog(tmp_path)
    _stamp_at_revision(catalog.db_path, "head")

    migrate_existing(catalog)

    assert _current_revision(catalog.db_path) == _head_revision(tmp_path)


def test_migrate_existing_upgrades_a_stale_catalog(tmp_path):
    catalog = _catalog(tmp_path)
    _stamp_at_revision(catalog.db_path, "a0982134c448")
    assert _current_revision(catalog.db_path) == "a0982134c448"

    migrate_existing(catalog)

    assert _current_revision(catalog.db_path) == _head_revision(tmp_path)
