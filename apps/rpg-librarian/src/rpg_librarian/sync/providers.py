"""Provider boundary: observation, version checks and verified downloads."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from rpg_librarian_tools.errors import SourceBudgetExceeded
from rpg_librarian_tools.onedrive import OneDrive

from ..batch.records import now
from ..errors import UsageError
from ..imports.auth import TokenProvider
from ..imports.discovery import content_version, discover
from ..imports.state import State
from ..infrastructure.walk import is_filtered
from .registry import Registry


@dataclass(frozen=True)
class RemoteFile:
    identity: str
    version: str
    path: str
    size: int

    def record(self) -> dict:
        return asdict(self)


class Provider(Protocol):
    def observe(self) -> list[RemoteFile]: ...
    def validate(self, item: RemoteFile) -> None: ...
    def download(self, item: RemoteFile, destination: Path) -> str: ...
    def close(self) -> None: ...


class OneDriveProvider:
    def __init__(
        self,
        registry: Registry,
        source: dict,
        state: State,
        deadline: float,
        diagnostic: Callable[[dict], None] | None = None,
    ):
        config = registry.config(source)
        self.credentials = TokenProvider(config)
        self.diagnostic = diagnostic
        self.client = OneDrive(
            self.access_token,
            config.drive,
            config.root,
            deadline,
            refresh_token=lambda: self.access_token(force_refresh=True),
            diagnostic=diagnostic,
        )
        self.state, self.deadline = state, deadline
        self.checked_parents: set[str] = set()

    def access_token(self, *, force_refresh: bool = False) -> str:
        previous = self.credentials.expires_at
        try:
            value = self.credentials.get(force_refresh=force_refresh)
        except Exception as error:
            if self.diagnostic:
                self.diagnostic(
                    {
                        "operation": "token",
                        "outcome": "failed",
                        "error_type": type(error).__name__,
                        "force_refresh": force_refresh,
                    }
                )
            raise
        if self.diagnostic and (
            previous != self.credentials.expires_at or force_refresh
        ):
            self.diagnostic(
                {
                    "operation": "token",
                    "outcome": "completed",
                    "force_refresh": force_refresh,
                    "expires_at_epoch": self.credentials.expires_at,
                    "renewed_at": now(),
                }
            )
        return value

    def observe(self) -> list[RemoteFile]:
        if "folder" not in self.client.metadata(self.client.root):
            raise RuntimeError("Registered source is no longer a folder.")
        if not discover(self.state, self.client, self.deadline):
            raise SourceBudgetExceeded(
                "Source discovery is incomplete; nothing admitted."
            )
        return [
            RemoteFile(r["id"], r["version"], r["path"], r["size"])
            for r in self.state.db.execute(
                "SELECT * FROM remote WHERE eligible=1 AND deleted=0 ORDER BY path,id"
            )
            if not any(is_filtered(Path(part)) for part in Path(r["path"]).parts)
        ]

    def validate(self, item: RemoteFile) -> None:
        if time.monotonic() >= self.deadline:
            raise SourceBudgetExceeded("Source time budget reached; progress saved.")
        actual = self.client.metadata(item.identity)
        row = self.state.db.execute(
            "SELECT data FROM remote WHERE id=?", (item.identity,)
        ).fetchone()
        if row is None:
            raise RuntimeError("Source observation missing; run discovery again.")
        recorded = json.loads(row[0])
        if (
            "deleted" in actual
            or content_version(actual) != item.version
            or actual.get("size") != item.size
        ):
            raise RuntimeError(
                "Source content changed; retry discovery on the next run."
            )
        if actual.get("name") != recorded.get("name") or actual.get(
            "parentReference", {}
        ).get("id") != recorded.get("parentReference", {}).get("id"):
            raise RuntimeError("Source moved or renamed since discovery.")
        parent = actual.get("parentReference", {}).get("id")
        visited: set[str] = set()
        while (
            parent and parent != self.client.root and parent not in self.checked_parents
        ):
            if parent in visited:
                raise RuntimeError("Source ancestry contains a cycle.")
            visited.add(parent)
            row = self.state.db.execute(
                "SELECT data FROM remote WHERE id=?", (parent,)
            ).fetchone()
            if row is None:
                raise RuntimeError("Source ancestry incomplete.")
            expected, current = json.loads(row[0]), self.client.metadata(parent)
            if (
                "deleted" in current
                or current.get("name", "").startswith("_")
                or current.get("name") != expected.get("name")
                or current.get("parentReference", {}).get("id")
                != expected.get("parentReference", {}).get("id")
            ):
                raise RuntimeError("Source ancestry changed; retry discovery.")
            parent = current.get("parentReference", {}).get("id")
        if not parent:
            raise RuntimeError("Source item left the registered folder.")
        self.checked_parents.update(visited)

    def download(self, item: RemoteFile, destination: Path) -> str:
        self.validate(item)
        digest = self.client.download(item.identity, destination, item.size)
        self.validate(item)
        return digest

    def close(self) -> None:
        self.client.close()


PROVIDERS = {"onedrive": OneDriveProvider}


def open_provider(
    registry: Registry,
    source: dict,
    state: State,
    deadline: float,
    diagnostic: Callable[[dict], None] | None = None,
) -> Provider:
    if source["provider"] not in PROVIDERS:
        raise UsageError(f"Unsupported source provider: {source['provider']}")
    return PROVIDERS[source["provider"]](registry, source, state, deadline, diagnostic)
