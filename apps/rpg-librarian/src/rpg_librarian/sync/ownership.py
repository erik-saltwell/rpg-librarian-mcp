"""Confirm local bytes by SHA-256; cache only against precise file freshness."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from rpg_librarian_tools.errors import SourceBudgetExceeded

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


def signature(path: Path, observed: os.stat_result | None = None) -> str:
    stat = observed if observed is not None else path.stat()
    return json.dumps(
        [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    )


@dataclass(frozen=True)
class Match:
    path: Path
    signature: str
    root_id: int
    file_id: int | None


class Ownership:
    def __init__(self, catalog: Path, inbox: Path, sizes: set[int], deadline: float):
        self.deadline, self.inbox, self.sizes = deadline, inbox, sizes
        self.by_size: dict[int, set[Path]] = defaultdict(set)
        self.hashed_bytes = 0
        self.indexed_files = 0
        self.inventory_built = False
        self.resources = ExitStack()
        self.db = self.resources.enter_context(readonly_connection(catalog))
        self.roots = {
            identity: Path(path)
            for identity, path in self.db.execute("SELECT id,path FROM root")
        }
        self.locations: dict[Path, tuple[int, int | None]] = {}
        self.verified: dict[Path, str] = {}
        self.safe_directories: dict[Path, bool] = {}
        self.cache = sqlite3.connect(
            catalog.parent / "imports" / "local-hashes.sqlite3"
        )
        os.chmod(catalog.parent / "imports" / "local-hashes.sqlite3", 0o600)
        self.cache.execute(
            "CREATE TABLE IF NOT EXISTS digest(path TEXT PRIMARY KEY, "
            "signature TEXT NOT NULL, sha256 TEXT NOT NULL)"
        )

    def safe_directory(self, path: Path) -> bool:
        """Check each ancestor once per run; never follow a substituted symlink."""
        if path in self.safe_directories:
            return self.safe_directories[path]
        self.check_time()
        try:
            mode = path.lstat().st_mode
            safe = stat.S_ISDIR(mode) and (
                path == path.parent or self.safe_directory(path.parent)
            )
        except (FileNotFoundError, NotADirectoryError):
            safe = False
        self.safe_directories[path] = safe
        return safe

    def inspect_file(self, path: Path, root_id: int) -> os.stat_result | None:
        root = self.roots.get(root_id)
        if root is None or not path.is_absolute() or not path.is_relative_to(root):
            return None
        relative = path.relative_to(root)
        if ".." in relative.parts or any(
            is_filtered(Path(part)) for part in relative.parts
        ):
            return None
        if not self.safe_directory(path.parent):
            return None
        observed = path.lstat()
        return observed if stat.S_ISREG(observed.st_mode) else None

    def confirm(self, binding: dict, size: int) -> Match | None:
        """Validate a known copy without building the local candidate inventory."""
        self.check_time()
        root_id, file_id = binding["root_id"], binding["file_id"]
        path = Path(binding["local_path"])
        if file_id is not None:
            row = self.db.execute(
                "SELECT root_id,relative_path,size_bytes,missing_since "
                "FROM file WHERE id=?",
                (file_id,),
            ).fetchone()
            if (
                not row
                or row[3] is not None
                or row[2] != size
                or row[0] not in self.roots
            ):
                return None
            root_id = row[0]
            path = self.roots[root_id] / row[1]
        try:
            observed = self.inspect_file(path, root_id)
            if observed is None or observed.st_size != size:
                return None
            before = signature(path, observed)
            if before == binding["signature"]:
                self.verified[path] = before
            elif self.digest(path) != binding["sha256"]:
                return None
            self.locations[path] = (root_id, file_id)
            return Match(path, self.verified[path], root_id, file_id)
        except (FileNotFoundError, NotADirectoryError):
            return None

    def prepare(self) -> None:
        """Only unresolved sizes need a broad catalog/inbox candidate search."""
        if self.inventory_built:
            return
        self.check_time()
        self.inventory_built = True
        sizes = sorted(self.sizes)
        for index in range(0, len(sizes), 400):
            self.check_time()
            chunk = sizes[index : index + 400]
            query = (
                "SELECT id,root_id,relative_path,size_bytes FROM file WHERE "
                "missing_since IS NULL AND size_bytes IN ("
                + ",".join("?" for _ in chunk)
                + ")"
            )
            for file_id, root_id, relative, size in self.db.execute(query, chunk):
                self.check_time()
                if root_id not in self.roots:
                    continue
                path = self.roots[root_id] / relative
                try:
                    if self.inspect_file(path, root_id):
                        self.by_size[size].add(path)
                        self.locations[path] = (root_id, file_id)
                except (FileNotFoundError, NotADirectoryError):
                    continue
        inbox_root = next(
            (i for i, path in self.roots.items() if path == self.inbox), None
        )
        if inbox_root is not None and self.safe_directory(self.inbox):
            for path in files_under(self.inbox):
                self.check_time()
                try:
                    size = path.stat().st_size
                    if size in self.sizes and self.inspect_file(path, inbox_root):
                        self.by_size[size].add(path)
                        self.locations.setdefault(path, (inbox_root, None))
                except (FileNotFoundError, NotADirectoryError):
                    continue
        self.indexed_files = sum(len(paths) for paths in self.by_size.values())

    def check_time(self) -> None:
        if time.monotonic() >= self.deadline:
            raise SourceBudgetExceeded(
                "Local ownership verification reached the source time budget."
            )

    def digest(self, path: Path) -> str:
        self.check_time()
        before = signature(path)
        stored = self.cache.execute(
            "SELECT signature,sha256 FROM digest WHERE path=?", (str(path),)
        ).fetchone()
        if stored and stored[0] == before:
            self.verified[path] = before
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
        self.verified[path] = before
        return value

    def match(self, digest: str, size: int) -> Match | None:
        self.prepare()
        for path in sorted(self.by_size[size]):
            self.check_time()
            try:
                root_id, file_id = self.locations[path]
                if (
                    self.inspect_file(path, root_id)
                    and path.stat().st_size == size
                    and self.digest(path) == digest
                ):
                    return Match(path, self.verified[path], root_id, file_id)
            except (FileNotFoundError, NotADirectoryError):
                continue
        return None

    def has_candidates(self, size: int) -> bool:
        self.prepare()
        for path in self.by_size[size]:
            try:
                root_id, _ = self.locations[path]
                observed = self.inspect_file(path, root_id)
                if observed is not None and observed.st_size == size:
                    return True
            except (FileNotFoundError, NotADirectoryError):
                continue
        return False

    def close(self) -> None:
        self.cache.close()
        self.resources.close()
