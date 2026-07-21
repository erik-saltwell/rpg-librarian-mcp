"""Configuration: the library location, plus .env loading for everything else."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

CATALOG_DIRNAME = ".catalog"


def load_env() -> str | None:
    """Load a .env file into ``os.environ``.

    Searches upward from the current working directory -- the library root the
    server was started in, not this repo. A missing .env is fine. Existing
    environment variables win over file values.

    Returns the path of the file that was loaded, or None.
    """
    path = find_dotenv(usecwd=True)
    if not path:
        return None
    load_dotenv(path, override=False)
    return path


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime settings for one library.

    The library root is the working directory the server was launched from --
    deliberately not configurable, so the library you are sitting in is the
    library you operate on.
    """

    library_root: Path

    @property
    def catalog_dir(self) -> Path:
        """The metadata store, always ``<library root>/.catalog``."""
        return self.library_root / CATALOG_DIRNAME

    @classmethod
    def from_cwd(cls) -> Config:
        return cls(library_root=Path(os.getcwd()).resolve())
