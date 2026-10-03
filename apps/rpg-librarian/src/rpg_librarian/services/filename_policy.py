"""Stable destination allocation shared by placement and production cleanup."""

from pathlib import Path, PurePosixPath

from ..paths import sanitize_filename


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
    occupied: dict[str, set[int | None]] = {}
    for file_id, path in current.items():
        occupied.setdefault(path.casefold(), set()).add(file_id)
    parents = {
        str(PurePosixPath(p).parent)
        for fid, p in desired.items()
        if current.get(fid) != p or len(occupied.get(p.casefold(), set())) > 1
    }
    catalog_paths = set(current.values())
    for parent in sorted(parents):
        directory = library / parent
        if not directory.is_dir():
            continue
        for child in directory.iterdir():
            actual = str(PurePosixPath(parent) / child.name)
            key = actual.casefold()
            if actual not in catalog_paths or child.is_dir():
                occupied.setdefault(key, set()).add(None)
    result: dict[int, str] = {}
    preferred = preferred or set()
    for file_id in sorted(
        desired, key=lambda i: (current.get(i) != desired[i], i not in preferred, i)
    ):
        path = PurePosixPath(desired[file_id])
        candidate = path
        number = 2
        while occupied.get(str(candidate).casefold(), set()) - {file_id}:
            candidate = path.with_name(sanitize_filename(path.name, number=number))
            number += 1
        result[file_id] = str(candidate)
        occupied.setdefault(str(candidate).casefold(), set()).add(file_id)
    return result
