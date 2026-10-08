"""Stable destination allocation shared by placement and production cleanup."""

from pathlib import Path, PurePosixPath

from ..paths import sanitize_filename


class PathAllocator:
    """Incremental allocation with one directory listing per destination parent."""

    def __init__(self, current: dict[int, str], library: Path) -> None:
        self.library = library
        self.current = current
        self.catalog_paths = set(current.values())
        self.occupied: dict[str, set[int | None]] = {}
        self.loaded_parents: set[str] = set()
        for file_id, path in current.items():
            self.occupied.setdefault(path.casefold(), set()).add(file_id)

    def reserve_parent(self, parent: str) -> None:
        if parent in self.loaded_parents:
            return
        self.loaded_parents.add(parent)
        directory = self.library / parent
        if not directory.is_dir():
            return
        for child in directory.iterdir():
            actual = str(PurePosixPath(parent) / child.name)
            if actual not in self.catalog_paths or child.is_dir():
                self.occupied.setdefault(actual.casefold(), set()).add(None)

    def allocate(self, file_id: int, desired: str) -> str:
        path = PurePosixPath(desired)
        if (
            self.current.get(file_id) != desired
            or len(self.occupied.get(desired.casefold(), set())) > 1
        ):
            self.reserve_parent(str(path.parent))
        candidate = path
        number = 2
        while self.occupied.get(str(candidate).casefold(), set()) - {file_id}:
            candidate = path.with_name(sanitize_filename(path.name, number=number))
            number += 1
        result = str(candidate)
        self.occupied.setdefault(result.casefold(), set()).add(file_id)
        return result


def allocate_paths(
    desired: dict[int, str],
    current: dict[int, str],
    library: Path,
    *,
    preferred: set[int] | None = None,
) -> dict[int, str]:
    """Reserve existing paths, then allocate compliant names before changed ones.

    Disk entries (including uncataloged files and directories) reserve names too.
    A file may retain its own current name; every other occupied name needs a suffix.
    """
    allocator = PathAllocator(current, library)
    parents = {
        str(PurePosixPath(p).parent)
        for fid, p in desired.items()
        if current.get(fid) != p or len(allocator.occupied.get(p.casefold(), set())) > 1
    }
    for parent in sorted(parents):
        allocator.reserve_parent(parent)
    result: dict[int, str] = {}
    preferred = preferred or set()
    for file_id in sorted(
        desired, key=lambda i: (current.get(i) != desired[i], i not in preferred, i)
    ):
        result[file_id] = allocator.allocate(file_id, desired[file_id])
    return result
