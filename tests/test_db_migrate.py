from importlib import resources

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


def test_migrate_existing_bootstraps_when_catalog_missing(tmp_path):
    catalog = Catalog(library_root=tmp_path)

    migrate_existing(catalog)

    assert catalog.db_path.exists()
    assert (tmp_path / "claude.md").exists()
    assert (
        tmp_path / ".claude" / "skills" / "rpg-librarian-mcp-test" / "SKILL.md"
    ).exists()


def test_migrate_existing_overwrites_claude_md(tmp_path):
    catalog = _catalog(tmp_path)
    claude_md_path = tmp_path / "claude.md"
    claude_md_path.write_text("stale content")

    migrate_existing(catalog)

    packaged = resources.files("rpg_librarian_mcp") / "resources" / "claude.md"
    assert claude_md_path.read_text(encoding="utf-8") == packaged.read_text(
        encoding="utf-8"
    )


def test_migrate_existing_resyncs_a_stale_skill_file(tmp_path):
    catalog = _catalog(tmp_path)
    skill_dir = tmp_path / ".claude" / "skills" / "rpg-librarian-mcp-test"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("stale skill content")
    (skill_dir / "stale_extra_file.md").write_text("should be removed")

    migrate_existing(catalog)

    packaged_skill_md = (
        resources.files("rpg_librarian_mcp")
        / "resources"
        / "skills"
        / "rpg-librarian-mcp-test"
        / "SKILL.md"
    )
    assert (skill_dir / "SKILL.md").read_text(
        encoding="utf-8"
    ) == packaged_skill_md.read_text(encoding="utf-8")
    assert not (skill_dir / "stale_extra_file.md").exists()


def test_migrate_existing_does_not_touch_a_users_own_custom_skill(tmp_path):
    catalog = _catalog(tmp_path)
    custom_skill_dir = tmp_path / ".claude" / "skills" / "my-own-skill"
    custom_skill_dir.mkdir(parents=True)
    (custom_skill_dir / "SKILL.md").write_text("my own skill, do not touch")

    migrate_existing(catalog)

    assert (custom_skill_dir / "SKILL.md").read_text() == "my own skill, do not touch"


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
