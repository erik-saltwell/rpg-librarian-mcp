"""Deep, atomic operations for inspecting and enriching RPG library files."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rpg-librarian-tools")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.0.0"

__all__ = ["__version__"]
