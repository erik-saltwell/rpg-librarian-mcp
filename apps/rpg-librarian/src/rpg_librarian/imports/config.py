from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..errors import UsageError


def setting(name: str) -> str:
    value = os.environ.get(f"RPG_LIBRARIAN_{name}", "").strip()
    if not value:
        raise UsageError(f"Set RPG_LIBRARIAN_{name} in the application's .env.")
    return value


@dataclass(frozen=True)
class Config:
    client: str
    authority: str
    scopes: list[str]
    cache: Path
    drive: str
    root: str

    @classmethod
    def load(cls) -> Config:
        return cls(
            setting("ONEDRIVE_CLIENT_ID"),
            os.environ.get(
                "RPG_LIBRARIAN_ONEDRIVE_AUTHORITY",
                "https://login.microsoftonline.com/consumers",
            ),
            os.environ.get(
                "RPG_LIBRARIAN_ONEDRIVE_SCOPES",
                (
                    "https://graph.microsoft.com/Files.Read.A"
                    "ll "
                    "https://graph.microsoft.com/User.Read"
                ),
            ).split(),
            Path(setting("ONEDRIVE_TOKEN_CACHE")).expanduser().resolve(),
            setting("ONEDRIVE_DRIVE_ID"),
            setting("ONEDRIVE_ROOT_ITEM_ID"),
        )
