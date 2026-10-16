"""CLI adapters for the source registry and serial nightly synchronization."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

from ..errors import UsageError
from ..imports.auth import token
from ..imports.state import State
from ..infrastructure.job_lock import catalog_job_lock
from ..sync.providers import open_provider
from ..sync.registry import Registry, valid_name
from ..sync.runner import run

__all__ = ["run", "source"]


def source(args: argparse.Namespace, catalog: Path) -> int:
    with catalog_job_lock(catalog):
        registry = Registry(catalog)
        registry.migrate_brendan()
        if args.action == "list":
            print(json.dumps(registry.data["sources"], indent=2))
            return 0
        if not args.name:
            raise UsageError("Specify the source name.")
        name = valid_name(args.name)
        if args.action == "add":
            account = args.account or "default-onedrive"
            profile = None
            if args.client_id or args.token_cache:
                if not args.client_id or not args.token_cache:
                    raise UsageError(
                        "Supply both --client-id and --token-cache for a new account."
                    )
                profile = {
                    "provider": "onedrive",
                    "client": args.client_id,
                    "cache": str(args.token_cache.expanduser().absolute()),
                    "authority": args.authority,
                    "scopes": args.scopes.split(),
                }
            elif account not in registry.data["accounts"]:
                client = os.environ.get("RPG_LIBRARIAN_ONEDRIVE_CLIENT_ID")
                cache = os.environ.get("RPG_LIBRARIAN_ONEDRIVE_TOKEN_CACHE")
                if client and cache:
                    profile = {
                        "provider": "onedrive",
                        "client": client,
                        "cache": str(Path(cache).expanduser().absolute()),
                        "authority": os.environ.get(
                            "RPG_LIBRARIAN_ONEDRIVE_AUTHORITY", args.authority
                        ),
                        "scopes": os.environ.get(
                            "RPG_LIBRARIAN_ONEDRIVE_SCOPES", args.scopes
                        ).split(),
                    }
            drive = args.drive_id or os.environ.get(
                "RPG_LIBRARIAN_ONEDRIVE_DRIVE_ID", ""
            )
            folder = args.folder_id or os.environ.get(
                "RPG_LIBRARIAN_ONEDRIVE_ROOT_ITEM_ID", ""
            )
            registry.add(
                name, account=account, drive=drive, folder=folder, profile=profile
            )
            print(f"Registered source {name} (onedrive).")
            return 0
        registered = registry.data["sources"].get(name)
        if registered is None:
            raise UsageError("Unknown source; run sync-source list.")
        if args.action in {"enable", "disable"}:
            registered["enabled"] = args.action == "enable"
            registry.save()
            print(f"{name}: {args.action}d")
        elif args.action == "auth":
            token(registry.config(registered), interactive=True)
            print(f"Authorization ready for {name}.")
        elif args.action == "doctor":
            state = State(catalog, name)
            provider = None
            try:
                provider = open_provider(
                    registry, registered, state, time.monotonic() + 120
                )
                # Observe through the provider boundary, saving a valid complete
                # cursor for the next sync without downloading or admitting files.
                items = provider.observe()
                print(f"{name}: source reachable; {len(items)} eligible file(s).")
            finally:
                if provider is not None:
                    provider.close()
                state.close()
        elif args.action == "status":
            path = registry.directory / f"{name}.sqlite3"
            result = {"name": name, **registered, "admission": None}
            if path.exists():
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                    row = db.execute(
                        "SELECT value FROM setting WHERE key='sync_admission'"
                    ).fetchone()
                    if row:
                        result["admission"] = json.loads(row[0])
            print(json.dumps(result, indent=2))
    return 0
