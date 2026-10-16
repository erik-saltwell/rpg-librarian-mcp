"""Observe new input before quick deduplication can move it away."""

from __future__ import annotations

import time
from pathlib import Path

from sqlmodel import select

from ..db import readonly_connection, session_scope
from ..errors import UsageError
from ..infrastructure.walk import walk_files
from ..model import Root, RootKind


def inspect(catalog: Path, root: Path, *, on_progress=None) -> dict:
    if on_progress is not None:
        on_progress(
            {
                "description": "Inspecting inbox",
                "detail": str(root),
                "updated_at": time.monotonic(),
            }
        )
    if not catalog.is_file():
        raise UsageError("The catalog does not exist. Run init first.")
    with session_scope(catalog) as session:
        roots = session.exec(select(Root)).all()
        staging = next(
            (
                r
                for r in roots
                if Path(r.path).resolve() == root and r.kind == RootKind.staging
            ),
            None,
        )
        if staging is None:
            raise UsageError(
                "--root must be a registered staging root; run add-source first."
            )
        if not root.is_dir():
            raise UsageError("The selected staging root is not reachable.")
        library = next((r for r in roots if r.kind == RootKind.library), None)
        if library is None or not Path(library.path).is_dir():
            raise UsageError("The catalog needs a reachable library root.")
        root_id = staging.id
    with readonly_connection(catalog) as db:
        known = {
            path: (size, mtime, sha)
            for path, size, mtime, sha in db.execute(
                "SELECT relative_path,size_bytes,mtime,sha256 FROM file "
                "WHERE root_id=?",
                (root_id,),
            )
        }
        failed = {
            r[0]
            for r in db.execute(
                "SELECT DISTINCT f.relative_path FROM file f "
                "JOIN entry en ON en.file_id=f.id "
                "JOIN error er ON er.entry_id=en.id WHERE f.root_id=? "
                "AND er.stage IN ('scan','metadata','text')",
                (root_id,),
            )
        }
    result = {"seen": 0, "new": 0, "changed": 0, "retry": 0, "unchanged": 0}
    for path in walk_files(root):
        result["seen"] += 1
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        previous = known.get(relative)
        if previous is None:
            result["new"] += 1
        elif previous[:2] != (stat.st_size, int(stat.st_mtime)):
            result["changed"] += 1
        elif previous[2] is None or relative in failed:
            result["retry"] += 1
        else:
            result["unchanged"] += 1
        if on_progress is not None:
            on_progress(
                {
                    "description": "Inspecting inbox",
                    "completed": result["seen"],
                    "total": None,
                    "unit": "files",
                    "detail": relative,
                    "updated_at": time.monotonic(),
                }
            )
    return result
