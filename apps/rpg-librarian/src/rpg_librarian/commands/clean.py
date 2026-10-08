"""Permanently empty known library trash buckets and reclaim catalog space."""

from __future__ import annotations

import argparse
import errno
import os
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import case, delete, update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from ..db import session_scope
from ..errors import UsageError
from ..model import Disposition, File, FolderJudgment, Pack, Root, RootKind
from ..observability import (
    FileTracker,
    log_call_fields,
    log_file_fields,
    mark_file_error,
)
from ..paths import TRASH_BUCKETS, TRASH_DIRNAME
from ..progress import track

_BUCKETS = frozenset(TRASH_BUCKETS.values())
_BATCH_SIZE = 256


@dataclass(frozen=True)
class Item:
    relative: str
    file_id: int | None
    signature: tuple[int, int, int, int, int] | None


@dataclass
class Stats:
    files_deleted: int = 0
    bytes_deleted: int = 0
    records_removed: int = 0
    packs_removed: int = 0
    duplicates_released: int = 0
    directories_removed: int = 0
    errors: int = 0
    catalog_bytes_before: int = 0
    catalog_bytes_after: int = 0
    compacted: bool = False
    dry_run: bool = False


def _in_trash(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (
        len(parts) > 2
        and parts[0] == TRASH_DIRNAME
        and parts[1] in _BUCKETS
        and ".." not in parts
    )


def _signature(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        s = path.lstat()
        return s.st_size, s.st_mtime_ns, s.st_dev, s.st_ino, s.st_mode
    except FileNotFoundError:
        return None


def _check_parents(library: Path, path: Path) -> None:
    """Never traverse a directory symlink, including the trash/bucket roots."""
    parent = library
    for part in path.relative_to(library).parts[:-1]:
        parent /= part
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise OSError(f"trash parent is not a real directory: {parent}")


def _collect(
    session: Session, library: Path, root_id: int
) -> tuple[list[Item], set[Path]]:
    files = session.exec(select(File).where(col(File.root_id) == root_id)).all()
    known = {f.relative_path: f.id for f in files if _in_trash(f.relative_path)}
    paths = set(known)
    directories: set[Path] = set()

    def fail(error: OSError) -> None:
        raise UsageError(f"Cannot enumerate trash: {error}") from error

    for bucket in sorted(_BUCKETS):
        top = library / TRASH_DIRNAME / bucket
        _check_parents(library, top)
        signature = _signature(top)
        if signature is None:
            continue
        if not stat.S_ISDIR(signature[4]):
            raise UsageError(f"Trash bucket is not a real directory: {top}")
        for folder, dirs, names in os.walk(top, onerror=fail, followlinks=False):
            parent = Path(folder)
            directories.add(parent)
            links = [name for name in dirs if (parent / name).is_symlink()]
            dirs[:] = sorted(name for name in dirs if name not in links)
            for name in [*names, *links]:
                paths.add((parent / name).relative_to(library).as_posix())
    items = []
    for relative in sorted(paths):
        path = library / relative
        # A catalog path underneath a directory link is blocked, not followed.
        try:
            _check_parents(library, path)
            signature = _signature(path)
        except OSError:
            signature = None
        items.append(Item(relative, known.get(relative), signature))
    return items, directories


def _kept(session: Session, file: File | None) -> bool:
    if file is None:
        return False
    if file.pack_id is not None:
        pack = session.get(Pack, file.pack_id)
        return pack is not None and pack.disposition is Disposition.keep
    return file.disposition is Disposition.keep


def _purge(session: Session, ids: list[int], pack_ids: set[int], stats: Stats) -> None:
    released = removed = packs_removed = 0
    if ids:
        # A surviving copy must not remain an automatic duplicate of a deleted
        # original: reorganize would otherwise trash the last available copy.
        refs = session.exec(
            select(File).where(col(File.duplicate_of_id).in_(ids))
        ).all()
        released = sum(
            f.id not in ids and f.disposition is Disposition.duplicate for f in refs
        )
        session.exec(
            update(File)
            .where(col(File.duplicate_of_id).in_(ids))
            .values(
                duplicate_of_id=None,
                # Hash-only duplicates may have no extraction. Force the next
                # scan to process the newly unfiled survivor rather than skip it.
                sha256=case(
                    (col(File.disposition) == Disposition.duplicate, None),
                    else_=col(File.sha256),
                ),
                disposition=case(
                    (
                        col(File.disposition) == Disposition.duplicate,
                        Disposition.unfiled.value,
                    ),
                    else_=col(File.disposition),
                ),
            )
            .execution_options(synchronize_session=False)
        )
        session.exec(
            delete(File)
            .where(col(File.id).in_(ids))
            .execution_options(synchronize_session=False)
        )
        removed = len(ids)
        for pack_id in pack_ids:
            if (
                session.exec(
                    select(File.id).where(col(File.pack_id) == pack_id)
                ).first()
                is not None
            ):
                continue
            session.exec(
                delete(FolderJudgment).where(col(FolderJudgment.pack_id) == pack_id)
            )
            session.exec(delete(Pack).where(col(Pack.id) == pack_id))
            packs_removed += 1
    session.commit()
    stats.records_removed += removed
    stats.packs_removed += packs_removed
    stats.duplicates_released += released


def _execute(
    session: Session, items: list[Item], library: Path, root_id: int, stats: Stats
) -> None:
    with track("clean trash", len(items)) as progress:
        for start in range(0, len(items), _BATCH_SIZE):
            # Hold the writer lock while deleting this batch, preventing a filing
            # decision from changing between checking a row and deleting its file.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            ids: list[int] = []
            pack_ids: set[int] = set()
            for index, item in enumerate(
                items[start : start + _BATCH_SIZE], start=start + 1
            ):
                path = library / item.relative
                with FileTracker(item.file_id, path, action="clean"):
                    try:
                        file = session.get(File, item.file_id) if item.file_id else None
                        if (
                            item.file_id is None
                            and session.exec(
                                select(File.id).where(
                                    col(File.root_id) == root_id,
                                    col(File.relative_path) == item.relative,
                                )
                            ).first()
                            is not None
                        ):
                            raise OSError("catalog record appeared; rerun clean")
                        if item.file_id and (
                            file is None
                            or file.root_id != root_id
                            or file.relative_path != item.relative
                        ):
                            raise OSError("catalog location changed; rerun clean")
                        if _kept(session, file):
                            raise OSError(
                                "file is marked keep; run reorganize "
                                "to move it out of trash first"
                            )
                        _check_parents(library, path)
                        signature = _signature(path)
                        if signature != item.signature:
                            raise OSError(
                                "trash file changed after enumeration; rerun clean"
                            )
                        if signature is not None:
                            if stat.S_ISDIR(signature[4]):
                                raise OSError("catalog file path is a directory")
                            path.unlink()
                            stats.files_deleted += 1
                            stats.bytes_deleted += signature[0]
                        if file is not None:
                            assert file.id is not None
                            ids.append(file.id)
                            if file.pack_id is not None:
                                pack_ids.add(file.pack_id)
                        log_file_fields(bytes_deleted=signature[0] if signature else 0)
                    except OSError as error:
                        stats.errors += 1
                        mark_file_error(str(error))
                        print(f"ERROR {path}: {error}")
                progress(index, item.relative, stats.errors)
            _purge(session, ids, pack_ids, stats)


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    stats = Stats(dry_run=args.dry_run)
    with session_scope(catalog_path, migrate=not args.dry_run) as session:
        stats.catalog_bytes_before = catalog_path.stat().st_size
        root = session.exec(
            select(Root).where(col(Root.kind) == RootKind.library)
        ).first()
        if root is None or not Path(root.path).is_dir():
            raise UsageError("The catalog's library root is not reachable.")
        assert root.id is not None
        root_id, library = root.id, Path(root.path)
        relative_catalog = (
            catalog_path.resolve().relative_to(library.resolve())
            if catalog_path.resolve().is_relative_to(library.resolve())
            else None
        )
        if relative_catalog is not None and _in_trash(relative_catalog.as_posix()):
            raise UsageError(
                "The catalog itself is inside a trash bucket; move it before cleaning."
            )
        try:
            items, directories = _collect(session, library, root_id)
        except OSError as error:
            raise UsageError(f"Cannot enumerate trash: {error}") from error
        if args.dry_run:
            for item in items:
                file = session.get(File, item.file_id) if item.file_id else None
                reason = None
                try:
                    _check_parents(library, library / item.relative)
                    if _signature(library / item.relative) != item.signature:
                        raise OSError("trash file changed after enumeration")
                    if item.signature and stat.S_ISDIR(item.signature[4]):
                        raise OSError("catalog file path is a directory")
                    if _kept(session, file):
                        raise OSError("marked keep; run reorganize first")
                except OSError as error:
                    reason = str(error)
                status = f"BLOCKED ({reason})" if reason else "DELETE"
                print(
                    f"{status} {library / item.relative}"
                    + (f" (file {item.file_id})" if item.file_id else " (uncataloged)")
                )
                stats.errors += status.startswith("BLOCKED")
            print(
                f"dry run: {len(items)} trash items, {len(directories)} directories, "
                f"{stats.errors} blocked; catalog would be compacted"
            )
            log_call_fields(**vars(stats), planned=len(items))
            return 1 if stats.errors else 0
        try:
            _execute(session, items, library, root_id, stats)
        except SQLAlchemyError as error:
            session.rollback()
            stats.errors += 1
            print(
                f"ERROR catalog cleanup: {error}; "
                "rerun clean to reconcile already-deleted trash files"
            )
        for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            try:
                _check_parents(library, directory)
                if directory.is_symlink():
                    continue
                directory.rmdir()
                stats.directories_removed += 1
            except FileNotFoundError:
                pass
            except OSError as error:
                if error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                    stats.errors += 1
                    print(f"ERROR removing directory {directory}: {error}")
    try:
        with closing(sqlite3.connect(catalog_path)) as connection:
            connection.execute("VACUUM")
        stats.compacted = True
    except sqlite3.Error as error:
        stats.errors += 1
        print(
            f"ERROR catalog compaction: {error}; "
            "cleanup is committed, rerun clean to compact"
        )
    stats.catalog_bytes_after = catalog_path.stat().st_size
    print(
        f"deleted {stats.files_deleted} files ({stats.bytes_deleted} bytes), "
        f"removed {stats.records_removed} file records "
        f"and {stats.packs_removed} packs, "
        f"released {stats.duplicates_released} surviving duplicates, "
        f"removed {stats.directories_removed} directories, errors {stats.errors}; "
        f"catalog {stats.catalog_bytes_before} -> {stats.catalog_bytes_after} bytes"
    )
    log_call_fields(**vars(stats))
    return 1 if stats.errors else 0
