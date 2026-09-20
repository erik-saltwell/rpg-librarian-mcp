"""Configuration: .env loading and catalog path resolution."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

CATALOG_ENV_VAR = "RPG_LIBRARIAN_CATALOG"
DEFAULT_CATALOG_FILENAME = "catalog.db"


def load_env() -> str | None:
    """Load a .env file into ``os.environ``; existing variables win.

    Returns the path of the file loaded, or None if there is none.
    """
    path = find_dotenv()
    if not path:
        return None
    load_dotenv(path, override=False)
    return path


def resolve_catalog_path(cli_value: Path | None) -> Path:
    """Return the absolute catalog path.

    Precedence: --catalog, then $RPG_LIBRARIAN_CATALOG, then ./catalog.db.
    """
    if cli_value is not None:
        return cli_value.expanduser().resolve()
    from_env = os.environ.get(CATALOG_ENV_VAR)
    if from_env:
        return Path(from_env).expanduser().resolve()
    return (Path.cwd() / DEFAULT_CATALOG_FILENAME).resolve()
