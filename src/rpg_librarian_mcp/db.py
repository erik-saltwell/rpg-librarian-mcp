from __future__ import annotations

import shutil
import sqlite3
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


def _create_default_claude_md(library_root: Path) -> None:
    """Seed a starter CLAUDE.md in the library root, if one isn't already there.

    Uppercase filename: this is Claude Code's own project-instructions
    convention, and filesystem lookups for it are case-sensitive on
    Linux/macOS -- a lowercase `claude.md` here would never actually get
    auto-loaded as project context.

    Never overwrites an existing file -- this only fills in a brand-new
    library's missing default, it's not a template to keep in sync.
    """
    claude_md_path = library_root / "CLAUDE.md"
    if claude_md_path.exists():
        return
    resource = resources.files("rpg_librarian_mcp") / "resources" / "CLAUDE.md"
    claude_md_path.write_text(resource.read_text(encoding="utf-8"), encoding="utf-8")


def _deploy_skills(library_root: Path, *, overwrite: bool) -> None:
    """Copy every packaged skill directory into the library's .claude/skills/.

    Skills to deploy are discovered by listing resources/skills/ -- adding a
    new skill to the package is just adding a new subdirectory there, no
    registration needed.

    With overwrite=False, a skill already present in the library is left
    alone (first-time seed). With overwrite=True, each bundled skill's
    directory is wiped and replaced wholesale, so stale/renamed files from an
    older packaged version don't linger; directories that don't correspond to
    a currently-packaged skill (a user's own custom skill) are never touched.
    """
    skills_dir = resources.files("rpg_librarian_mcp") / "resources" / "skills"
    with resources.as_file(skills_dir) as packaged_skills_path:
        if not packaged_skills_path.is_dir():
            return
        target_root = library_root / ".claude" / "skills"
        for packaged_skill in sorted(packaged_skills_path.iterdir()):
            if not packaged_skill.is_dir():
                continue
            target_skill = target_root / packaged_skill.name
            if target_skill.exists():
                if not overwrite:
                    continue
                shutil.rmtree(target_skill)
            target_skill.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(packaged_skill, target_skill)


def ensure_bootstrapped(catalog: Catalog) -> None:
    if not catalog.catalog_dir.exists():
        catalog.catalog_dir.mkdir(parents=True)
        _create_default_claude_md(catalog.library_root)
        _deploy_skills(catalog.library_root, overwrite=False)
    if not catalog.db_path.exists():
        _setup_db(catalog.db_path)


def migrate_existing(catalog: Catalog) -> None:
    """Explicit sync path: bring the current directory fully up to date.

    Creates anything missing (.catalog, CLAUDE.md, the db) just like a
    first run would, then force-syncs CLAUDE.md and every packaged skill to
    the currently installed version, and upgrades the schema to head.
    """
    ensure_bootstrapped(catalog)

    claude_md_path = catalog.library_root / "CLAUDE.md"
    legacy_claude_md_path = catalog.library_root / "claude.md"
    # A library bootstrapped before CLAUDE.md's uppercase rename has a
    # lowercase leftover. On a case-sensitive filesystem this is a distinct,
    # separate file from `claude_md_path` (remove it -- CLAUDE.md is about
    # to be (re)written below anyway, matching "fully up to date", not two
    # instruction files where only one is ever auto-loaded). On a
    # case-insensitive filesystem the two paths already resolve to the same
    # file, so this is a no-op.
    if (
        legacy_claude_md_path.exists()
        and legacy_claude_md_path.resolve() != claude_md_path.resolve()
    ):
        legacy_claude_md_path.unlink()

    resource = resources.files("rpg_librarian_mcp") / "resources" / "CLAUDE.md"
    (catalog.library_root / "CLAUDE.md").write_text(
        resource.read_text(encoding="utf-8"), encoding="utf-8"
    )
    _deploy_skills(catalog.library_root, overwrite=True)
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


@contextmanager
def readonly_connection(catalog: Catalog) -> Generator[sqlite3.Connection]:
    """A connection to the catalog db that SQLite itself refuses to write through."""
    ensure_bootstrapped(catalog)
    uri = f"{catalog.db_path.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        yield conn
    finally:
        conn.close()
