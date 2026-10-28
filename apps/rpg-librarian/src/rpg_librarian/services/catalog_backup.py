"""Keep one consistent copy of the catalog inside the library's backed-up share."""

from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlmodel import select

from ..db import session_scope
from ..model import Root, RootKind

BACKUP_DIRNAME = ".backups"  # Dot-directories are never catalogued.


def backup_catalog(catalog: Path) -> Path:
    """Replace `<library>/.backups/<catalog name>` with a fresh snapshot."""
    with session_scope(catalog, migrate=False) as session:
        library = session.exec(
            select(Root.path).where(Root.kind == RootKind.library)
        ).first()
    if library is None or not Path(library).is_dir():
        raise RuntimeError("No reachable library root for the catalog backup.")
    directory = Path(library) / BACKUP_DIRNAME
    directory.mkdir(exist_ok=True)
    target = directory / catalog.name
    # Snapshot locally first: SQLite locking is unreliable on network shares.
    local = catalog.with_name(catalog.name + ".backup-partial")
    remote = target.with_name(target.name + ".partial")
    try:
        local.unlink(missing_ok=True)
        with (
            closing(sqlite3.connect(catalog)) as source,
            closing(sqlite3.connect(local)) as snapshot,
        ):
            source.backup(snapshot)
        shutil.copyfile(local, remote)
        # The previous copy survives until the new one is complete.
        os.replace(remote, target)
    finally:
        local.unlink(missing_ok=True)
        remote.unlink(missing_ok=True)
    return target
