"""Confirm local bytes by SHA-256; cache only against precise file freshness."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from ..db import readonly_connection
from ..errors import UsageError
from ..imports.transfer import file_hash
from ..infrastructure.walk import is_filtered


def files_under(root: Path):
    """No symlink traversal, including symlink files."""
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(
            d for d in dirs if not is_filtered(base / d) and not (base / d).is_symlink()
        )
        for name in sorted(files):
            path = base / name
            if not is_filtered(path) and not path.is_symlink() and path.is_file():
                yield path


def signature(path: Path) -> str:
    stat = path.stat()
    return json.dumps(
        [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    )


class Ownership:
    def __init__(self, catalog: Path, inbox: Path, sizes: set[int], deadline: float):
        self.deadline = deadline
        self.by_size: dict[int, set[Path]] = defaultdict(set)
        self.hashed_bytes = 0
        self.cache = sqlite3.connect(
            catalog.parent / "imports" / "local-hashes.sqlite3"
        )
        os.chmod(catalog.parent / "imports" / "local-hashes.sqlite3", 0o600)
        self.cache.execute(
            "CREATE TABLE IF NOT EXISTS digest(path TEXT PRIMARY KEY, "
            "signature TEXT NOT NULL, sha256 TEXT NOT NULL)"
        )
        if not sizes:
            return
        with readonly_connection(catalog) as db:
            roots = dict(db.execute("SELECT id,path FROM root"))
            for index in range(0, len(sizes), 400):
                chunk = sorted(sizes)[index : index + 400]
                query = (
                    "SELECT root_id,relative_path,size_bytes FROM file WHERE "
                    "missing_since IS NULL AND size_bytes IN ("
                    + ",".join("?" for _ in chunk)
                    + ")"
                )
                for root_id, relative, size in db.execute(query, chunk):
                    root = Path(roots[root_id])
                    path = root / relative
                    # Do not hash trash or paths escaping a registered root.
                    if any(is_filtered(Path(part)) for part in Path(relative).parts):
                        continue
                    if (
                        path.is_absolute()
                        and path.resolve().is_relative_to(root.resolve())
                        and not path.is_symlink()
                    ):
                        self.by_size[size].add(path)
        for path in files_under(inbox):
            self.check_time()
            size = path.stat().st_size
            if size in sizes:
                self.by_size[size].add(path)

    def check_time(self) -> None:
        if time.monotonic() >= self.deadline:
            raise TimeoutError(
                "Local ownership verification reached the source time budget."
            )

    def digest(self, path: Path) -> str:
        self.check_time()
        before = signature(path)
        stored = self.cache.execute(
            "SELECT signature,sha256 FROM digest WHERE path=?", (str(path),)
        ).fetchone()
        if stored and stored[0] == before:
            return stored[1]
        value = file_hash(path)
        self.hashed_bytes += path.stat().st_size
        if signature(path) != before:
            raise UsageError("Local file changed while hashing; rerun sync.")
        with self.cache:
            self.cache.execute(
                "INSERT OR REPLACE INTO digest VALUES(?,?,?)",
                (str(path), before, value),
            )
        return value

    def match(self, digest: str, size: int) -> Path | None:
        for path in sorted(self.by_size[size]):
            self.check_time()
            try:
                if (
                    path.is_file()
                    and path.stat().st_size == size
                    and self.digest(path) == digest
                ):
                    return path
            except FileNotFoundError:
                continue
        return None

    def has_candidates(self, size: int) -> bool:
        return any(p.is_file() and p.stat().st_size == size for p in self.by_size[size])

    def close(self) -> None:
        self.cache.close()
