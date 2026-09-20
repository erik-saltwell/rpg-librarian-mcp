from __future__ import annotations


class UsageError(Exception):
    """A problem the user can fix; the CLI prints it and exits 1, with no traceback."""


class CatalogNotFoundError(UsageError):
    """The catalog database does not exist yet."""

    def __init__(self, path: object) -> None:
        super().__init__(f"No catalog at {path}. Run `rpg-librarian init` first.")
