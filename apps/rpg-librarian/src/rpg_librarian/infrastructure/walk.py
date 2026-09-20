from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from ..paths import TRASH_DIRNAME

# Dotfiles and dot-directories are never catalogued; that also covers `.trash`,
# but the trash folder is named explicitly so the rule survives a rename.
_FILTERED_PREFIXES: tuple[str, ...] = (".",)
_FILTERED_NAMES: frozenset[str] = frozenset({TRASH_DIRNAME, "agents.md", "claude.md"})


def is_filtered(path: Path) -> bool:
    name = path.name
    return name.lower() in _FILTERED_NAMES or name.startswith(_FILTERED_PREFIXES)


def walk_files(root: Path) -> Generator[Path]:
    """Yield every catalogable file under `root`, depth-first in sorted order."""
    entries = sorted(root.iterdir())
    yield from (p for p in entries if p.is_file() and not is_filtered(p))
    for directory in (p for p in entries if p.is_dir() and not is_filtered(p)):
        yield from walk_files(directory)
