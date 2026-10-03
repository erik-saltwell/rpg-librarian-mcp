"""Preview or apply filename-only cleanup, with backup and durable rename journal."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TypedDict

from sqlmodel import select

from ..db import readonly_connection, session_scope
from ..errors import UsageError
from ..model import File, Root, RootKind
from ..paths import sanitize_filename
from ..services.file_moves import rename_no_replace
from ..services.filename_policy import allocate_paths


class Change(TypedDict):
    file_id: int
    old_path: str
    new_path: str
    old_subpath: str | None
    new_subpath: str | None


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Clean library basenames only; leave folders, decisions and staging untouched."""
    with session_scope(catalog_path, migrate=False) as session:
        root = next(
            (r for r in session.exec(select(Root)).all() if r.kind is RootKind.library),
            None,
        )
        if root is None or not Path(root.path).is_dir():
            raise UsageError("The catalog's library root is not reachable")
        library = Path(root.path)
        files = session.exec(select(File).where(File.root_id == root.id)).all()
        current = {f.id: f.relative_path for f in files if f.id is not None}
        desired = {
            fid: str(
                PurePosixPath(p).with_name(sanitize_filename(PurePosixPath(p).name))
            )
            for fid, p in current.items()
        }
        allocated = allocate_paths(desired, current, library)
        changes: list[Change] = []
        blocked: list[dict[str, object]] = []
        for file in sorted(files, key=lambda f: f.id or 0):
            assert file.id is not None
            dest = allocated[file.id]
            subpath = file.subpath
            if subpath is not None:
                old_name = PurePosixPath(file.relative_path).name
                new_name = (
                    PurePosixPath(dest).name
                    if PurePosixPath(subpath).name == old_name
                    else sanitize_filename(PurePosixPath(subpath).name)
                )
                subpath = str(PurePosixPath(subpath).with_name(new_name))
            if dest == file.relative_path and subpath == file.subpath:
                continue
            source = library / file.relative_path
            reason = None
            if file.missing_since is not None:
                reason = "catalog marks the file missing"
            elif not source.resolve().is_relative_to(library.resolve()):
                reason = "source is outside the library"
            elif source.is_symlink():
                reason = "source is a symbolic link"
            else:
                try:
                    stat = source.stat()
                    if not source.is_file():
                        reason = "source is not a regular file"
                    elif (stat.st_size, int(stat.st_mtime)) != (
                        file.size_bytes,
                        file.mtime,
                    ):
                        reason = "source size or modified time differs; scan first"
                except OSError as error:
                    reason = str(error)
            change: Change = {
                "file_id": file.id,
                "old_path": file.relative_path,
                "new_path": dest,
                "old_subpath": file.subpath,
                "new_subpath": subpath,
            }
            if reason:
                blocked.append({**change, "reason": reason})
            else:
                changes.append(change)
        report = {
            "catalog": str(catalog_path.resolve()),
            "library": str(library),
            "changes": changes,
            "blocked": blocked,
        }
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"Filename cleanup: {len(changes)} changes, {len(blocked)} blocked")
        for change in changes:
            print(f"  {change['old_path']} -> {change['new_path']}")
        for failure in blocked:
            print(f"  BLOCKED {failure['old_path']}: {failure['reason']}")
        if not args.apply or not changes:
            return 1 if blocked else 0
        if blocked:
            raise UsageError("Cleanup has blocked files; nothing applied")

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = catalog_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{catalog_path.stem}-before-filename-cleanup-{stamp}.db"
        with (
            readonly_connection(catalog_path) as source_db,
            closing(sqlite3.connect(backup)) as backup_db,
        ):
            source_db.backup(backup_db)
        journal = backup.with_suffix(".jsonl")
        print(f"Backup: {backup}\nRename journal: {journal}")
        by_id = {f.id: f for f in files}
        with journal.open("x") as log:

            def record(event: dict[str, object]) -> None:
                log.write(json.dumps(event, ensure_ascii=False) + "\n")
                log.flush()
                os.fsync(log.fileno())

            record({"event": "plan", **report})
            for change in changes:
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                file = by_id[change["file_id"]]
                session.refresh(file)
                if (file.relative_path, file.subpath) != (
                    change["old_path"],
                    change["old_subpath"],
                ):
                    raise UsageError(
                        "Catalog paths changed during cleanup; rerun preview"
                    )
                source = library / change["old_path"]
                destination = library / change["new_path"]
                # Check again immediately before each move, after the backup.
                stat = source.stat()
                if (stat.st_size, int(stat.st_mtime)) != (file.size_bytes, file.mtime):
                    raise UsageError(f"Source changed during cleanup: {source}")
                moved = source != destination
                record({"event": "starting", **change})
                if moved:
                    rename_no_replace(source, destination)
                try:
                    file.relative_path = change["new_path"]
                    file.subpath = change["new_subpath"]
                    file.last_seen_at = datetime.now(UTC)
                    session.add(file)
                    session.commit()
                except BaseException:
                    session.rollback()
                    if moved:
                        rename_no_replace(destination, source)
                    record({"event": "rolled_back", **change})
                    raise
                record({"event": "complete", **change})
        print(f"Applied {len(changes)} filename changes")
    return 0
