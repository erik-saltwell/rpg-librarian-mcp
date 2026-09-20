from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

filtered_names: tuple[str, ...] = ("agents.md", "claude.md")
filtered_prefixes: tuple[str, ...] = (".",)


def is_filtered(path: Path) -> bool:
    name_with_extension: str = path.name
    # Case-insensitive: AGENTS.md/CLAUDE.md are conventionally uppercase,
    # but this must also still catch a pre-existing lowercase file from
    # before that convention was applied here.
    if name_with_extension.lower() in filtered_names:
        return True
    return bool(
        any(name_with_extension.startswith(prefix) for prefix in filtered_prefixes)
    )


def walk_filesystem(starting_path: Path, recurse: bool) -> Generator[Path]:
    if not starting_path.exists():
        raise ValueError(f"{starting_path} does not exist")
    if starting_path.is_file():
        yield starting_path
    else:
        yield from sorted(
            path
            for path in starting_path.iterdir()
            if path.is_file() and not is_filtered(path)
        )
        if recurse:
            for dir in sorted(
                path
                for path in starting_path.iterdir()
                if path.is_dir() and not is_filtered(path)
            ):
                yield from walk_filesystem(dir, recurse)


def walk_directories(starting_path: Path) -> Generator[Path]:
    """Yield every directory under `starting_path`, recursively (not itself)."""
    for path in sorted(starting_path.iterdir()):
        if path.is_dir() and not is_filtered(path):
            yield path
            yield from walk_directories(path)
