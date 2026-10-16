"""Catalog-bound named sources and reusable account profiles (never token contents)."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from ..batch.records import write_json
from ..errors import UsageError
from ..imports.config import Config


def valid_name(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", value):
        raise UsageError(
            "Names must start with a lowercase letter and contain only "
            "a-z, 0-9 or hyphens (max 63 characters)."
        )
    return value


class Registry:
    def __init__(self, catalog: Path):
        if not catalog.is_file():
            raise UsageError("The catalog does not exist. Specify --catalog.")
        self.catalog = catalog.resolve()
        self.directory = catalog.parent / "imports"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.path = self.directory / "sources.json"
        self.data: dict = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "version": 1,
                "catalog": str(self.catalog),
                "accounts": {},
                "sources": {},
            }
        )
        if self.data.get("version") != 1 or self.data.get("catalog") != str(
            self.catalog
        ):
            raise UsageError("Source registry version/catalog does not match.")

    def save(self) -> None:
        write_json(self.path, self.data)

    def migrate_brendan(self) -> bool:
        """Adopt identity; revision history stays in its original journal."""
        if "brendan" in self.data["sources"]:
            return False
        journal = self.directory / "brendan.sqlite3"
        if not journal.exists():
            return False
        with sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT value FROM setting WHERE key='source'").fetchone()
            bound = db.execute(
                "SELECT value FROM setting WHERE key='catalog'"
            ).fetchone()
        if bound and Path(json.loads(bound[0])).resolve() != self.catalog:
            raise UsageError("Legacy Brendan journal belongs to another catalog.")
        if not row:
            return False
        identity = json.loads(row[0])
        # A missing credential profile becomes a per-source error during execution;
        # it must not prevent other registered sources from running.
        self.data["accounts"].setdefault(
            "legacy-onedrive", {"provider": "onedrive", "environment": True}
        )
        self.data["sources"]["brendan"] = {
            "provider": "onedrive",
            "account": "legacy-onedrive",
            "drive": identity["drive"],
            "folder": identity["root"],
            "enabled": True,
            "legacy_inbox": identity["inbox"],
        }
        self.save()
        return True

    def config(self, source: dict) -> Config:
        account = self.data["accounts"][source["account"]]
        if account.get("environment"):
            old = Config.load()
            return Config(
                old.client,
                old.authority,
                old.scopes,
                old.cache,
                source["drive"],
                source["folder"],
            )
        return Config(
            account["client"],
            account["authority"],
            account["scopes"],
            Path(account["cache"]),
            source["drive"],
            source["folder"],
        )

    def add(
        self, name: str, *, account: str, drive: str, folder: str, profile: dict | None
    ) -> None:
        valid_name(name)
        valid_name(account)
        previous = self.data["sources"].get(name)
        identity = {
            "provider": "onedrive",
            "account": account,
            "drive": drive,
            "folder": folder,
        }
        if previous and any(previous[k] != v for k, v in identity.items()):
            raise UsageError(
                "Registered source identity cannot change; choose a new source name."
            )
        if profile is not None:
            existing = self.data["accounts"].get(account)
            if existing and existing != profile:
                raise UsageError("Account profile differs; choose a new account name.")
            self.data["accounts"][account] = profile
        if account not in self.data["accounts"]:
            raise UsageError(
                "New accounts need --client-id and --token-cache, or "
                "configured OneDrive environment settings."
            )
        if not drive or not folder:
            raise UsageError("Specify nonempty --drive-id and --folder-id.")
        self.data["sources"][name] = {
            **identity,
            "enabled": previous.get("enabled", True) if previous else True,
            **(
                {"legacy_inbox": previous["legacy_inbox"]}
                if previous and "legacy_inbox" in previous
                else {}
            ),
        }
        self.save()
