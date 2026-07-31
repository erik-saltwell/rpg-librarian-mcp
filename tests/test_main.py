from importlib import resources

from alembic import command
from alembic.config import Config

from rpg_librarian_mcp.__main__ import main
from rpg_librarian_mcp.catalog import Catalog


def _bootstrap_catalog(tmp_path) -> None:
    catalog = Catalog(library_root=tmp_path)
    catalog.catalog_dir.mkdir(parents=True)
    alembic_dir = resources.files("rpg_librarian_mcp") / "alembic"
    with resources.as_file(alembic_dir) as alembic_path:
        cfg = Config(str(alembic_path / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{catalog.db_path}")
        command.upgrade(cfg, "head")


def test_migrate_flag_bootstraps_a_fresh_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["rpg-librarian-mcp", "--migrate"])

    main()  # should not raise

    assert (tmp_path / ".catalog" / "catalog.db").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (
        tmp_path / ".claude" / "skills" / "rpg-librarian-mcp-test" / "SKILL.md"
    ).exists()


def test_migrate_flag_succeeds_for_existing_catalog(tmp_path, monkeypatch):
    _bootstrap_catalog(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["rpg-librarian-mcp", "--migrate"])

    main()  # should not raise
