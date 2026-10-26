"""Exact classification, whole-source admission and crash-resumable publication."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path

from rpg_librarian_tools.errors import SourceBudgetExceeded
from rpg_librarian_tools.onedrive import TRANSIENT, GraphError

from ..batch.records import now
from ..errors import UsageError
from ..imports.state import State
from ..imports.transfer import destination_path, file_hash
from ..services.file_moves import rename_no_replace
from .ownership import Match, Ownership
from .providers import Provider, RemoteFile


class Ingestion:
    def __init__(
        self,
        name: str,
        state: State,
        provider: Provider | None,
        inbox: Path,
        max_cache_bytes: int,
        deadline: float,
        result: dict,
        save,
    ):
        self.name, self.state, self.provider = name, state, provider
        self.inbox, self.max_cache_bytes, self.deadline = (
            inbox,
            max_cache_bytes,
            deadline,
        )
        self.result, self.save = result, save
        self.cache = state.directory / "cache" / name
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Downloads run in the coordinator, so under its catalog lock any partial
        # here belongs to a dead run. Do not let changed versions leak disk space.
        for partial in self.cache.glob("*.part"):
            partial.unlink()
        if state.get("sync_schema_version", 1) != 1:
            raise UsageError("Source sync journal requires a different app version.")
        state.set("sync_schema_version", 1)
        state.db.execute(
            "CREATE TABLE IF NOT EXISTS sync_content(remote_id TEXT NOT "
            "NULL, version TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY "
            "KEY(remote_id,version))"
        )
        # Only historical downloads/exact comparisons seed proofs; metadata guesses
        # deliberately do not. Local bytes must still be confirmed before exclusion.
        state.db.execute(
            "INSERT OR IGNORE INTO sync_content SELECT "
            "remote_id,version,sha256 FROM revision WHERE sha256 IS NOT "
            "NULL AND (method='sha256' OR status IN "
            "('publishing','published','processed'))"
        )
        state.db.execute(
            "CREATE TABLE IF NOT EXISTS sync_ownership("
            "remote_id TEXT NOT NULL, version TEXT NOT NULL, sha256 TEXT NOT NULL, "
            "root_id INTEGER NOT NULL, file_id INTEGER, local_path TEXT NOT NULL, "
            "signature TEXT NOT NULL, reconciled_at REAL NOT NULL, "
            "PRIMARY KEY(remote_id,version))"
        )
        state.db.commit()

    def checkpoint(self) -> None:
        self.state.db.commit()
        self.save()

    def check_time(self) -> None:
        if time.monotonic() >= self.deadline:
            raise SourceBudgetExceeded("Source time budget reached; progress saved.")

    def cached(self, item: RemoteFile) -> Path:
        key = hashlib.sha256(f"{item.identity}:{item.version}".encode()).hexdigest()
        return self.cache / (key + ".data")

    def proof(self, item: RemoteFile) -> str | None:
        row = self.state.db.execute(
            "SELECT sha256 FROM sync_content WHERE remote_id=? AND version=?",
            (item.identity, item.version),
        ).fetchone()
        return row[0] if row else None

    def make_space(self, required: int, protected: set[Path]) -> None:
        if required > self.max_cache_bytes:
            raise UsageError(
                "A source file exceeds --max-cache-bytes; increase the limit "
                "or import it manually."
            )
        files = sorted(self.cache.glob("*.data"), key=lambda p: p.stat().st_mtime)
        used = sum(p.stat().st_size for p in files)
        for path in files:
            if used + required <= self.max_cache_bytes:
                break
            if path not in protected:
                used -= path.stat().st_size
                path.unlink()
        if used + required > self.max_cache_bytes:
            raise UsageError(
                "Admitted batch exceeds --max-cache-bytes; increase the "
                "limit. Nothing new was published."
            )
        if shutil.disk_usage(self.cache).free < required + 16 * 1024**2:
            raise UsageError("Insufficient free space for source staging.")

    def download(
        self, item: RemoteFile, protected: set[Path] | None = None
    ) -> tuple[Path, str]:
        self.check_time()
        self.result["current_item"] = item.record()
        path, digest = self.cached(item), self.proof(item)
        if path.exists():
            if (
                not path.is_symlink()
                and path.stat().st_size == item.size
                and digest
                and file_hash(path) == digest
            ):
                self.result["cache_hits"] = self.result.get("cache_hits", 0) + 1
                return path, digest
            path.unlink()
        self.make_space(item.size, protected or set())
        partial = path.with_suffix(".part")
        partial.unlink(missing_ok=True)
        try:
            assert self.provider is not None
            computed = self.provider.download(item, partial)
            if partial.stat().st_size != item.size or file_hash(partial) != computed:
                raise RuntimeError(
                    "Provider download failed local hash/size verification."
                )
            if digest and computed != digest:
                raise RuntimeError(
                    "Provider returned different bytes for a previously verified "
                    "content version."
                )
            os.chmod(partial, 0o600)
            os.replace(partial, path)
            self.state.db.execute(
                "INSERT OR REPLACE INTO sync_content VALUES(?,?,?)",
                (item.identity, item.version, computed),
            )
            self.result["downloaded_files"] += 1
            self.result["downloaded_bytes"] += item.size
            self.checkpoint()
            return path, computed
        finally:
            partial.unlink(missing_ok=True)

    def remember_match(
        self, item: RemoteFile, match: Match, digest: str, reconciled_at: float
    ) -> None:
        self.state.db.execute(
            "INSERT INTO sync_ownership VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(remote_id,version) DO UPDATE SET "
            "sha256=excluded.sha256,root_id=excluded.root_id,file_id=excluded.file_id,"
            "local_path=excluded.local_path,signature=excluded.signature,"
            "reconciled_at=max(sync_ownership.reconciled_at,excluded.reconciled_at)",
            (
                item.identity,
                item.version,
                digest,
                match.root_id,
                match.file_id,
                str(match.path),
                match.signature,
                reconciled_at,
            ),
        )

    def classify(
        self, catalog: Path, items: list[RemoteFile], *, full_reconcile: bool = False
    ) -> list[RemoteFile]:
        started = time.monotonic()
        now_epoch = time.time()
        last_full = self.state.get("sync_last_full_reconcile", 0)
        epoch = self.state.get("sync_reconcile_started", 0)
        if not epoch and (full_reconcile or now_epoch - last_full >= 7 * 86400):
            epoch = now_epoch
            self.state.set("sync_reconcile_started", epoch)
            self.state.db.commit()
        bindings = {
            (row["remote_id"], row["version"]): dict(row)
            for row in self.state.db.execute("SELECT * FROM sync_ownership")
        }
        self.result.update(
            phase="classification",
            observed=len(items),
            examined=0,
            owned=0,
            pending=None,
            pending_so_far=0,
            unresolved=0,
            unresolved_items=[],
            classification_mode="full" if epoch else "incremental",
            ownership_reused=0,
            ownership_reclassified=0,
        )
        self.save()
        ownership = Ownership(catalog, self.inbox, set(), self.deadline)
        try:
            pending = []
            unmatched = []
            for item in items:
                self.result["current_item"] = item.record()
                self.check_time()
                destination_path(self.inbox / self.name, item.path)
                if any(part.startswith(".") for part in Path(item.path).parts):
                    raise UsageError(
                        "Source contains a hidden path that the batch scanner cannot "
                        "process."
                    )
                binding = bindings.get((item.identity, item.version))
                match = None
                if binding and (not epoch or binding["reconciled_at"] >= epoch):
                    match = ownership.confirm(binding, item.size)
                if match and binding:
                    if (
                        str(match.path) != binding["local_path"]
                        or match.signature != binding["signature"]
                        or match.root_id != binding["root_id"]
                        or match.file_id != binding["file_id"]
                    ):
                        self.remember_match(
                            item, match, binding["sha256"], binding["reconciled_at"]
                        )
                    self.result["owned"] += 1
                    self.result["ownership_reused"] += 1
                    self.result["examined"] += 1
                    if self.result["examined"] % 100 == 0:
                        self.checkpoint()
                else:
                    unmatched.append(item)
            ownership.sizes = {item.size for item in unmatched}
            consecutive_failures = 0
            for item in unmatched:
                self.result["ownership_reclassified"] += 1
                self.result["current_item"] = item.record()
                self.check_time()
                digest = self.proof(item)
                if digest is None and ownership.has_candidates(item.size):
                    try:
                        _, digest = self.download(item)
                    except (GraphError, ConnectionError) as error:
                        if (
                            isinstance(error, GraphError)
                            and error.status not in TRANSIENT
                        ):
                            raise
                        self.result["unresolved"] += 1
                        if len(self.result["unresolved_items"]) < 100:
                            self.result["unresolved_items"].append(
                                {
                                    **item.record(),
                                    "error_type": type(error).__name__,
                                    "status": getattr(error, "status", None),
                                }
                            )
                        self.result["examined"] += 1
                        consecutive_failures += 1
                        self.save()
                        if consecutive_failures >= 3:
                            raise ConnectionError(
                                "Three consecutive files exhausted transfer retries; "
                                "source paused, progress saved, nothing admitted."
                            ) from None
                        continue
                match = ownership.match(digest, item.size) if digest else None
                if match and digest:
                    self.remember_match(item, match, digest, epoch or now_epoch)
                    self.result["owned"] += 1
                else:
                    self.state.db.execute(
                        "DELETE FROM sync_ownership WHERE remote_id=? AND version=?",
                        (item.identity, item.version),
                    )
                    pending.append(item)
                consecutive_failures = 0
                self.result["examined"] += 1
                self.result["pending_so_far"] = len(pending)
                if self.result["examined"] % 100 == 0:
                    self.checkpoint()
            if self.result["unresolved"]:
                raise ConnectionError(
                    f"Classification has {self.result['unresolved']} "
                    "unresolved file(s); "
                    "nothing admitted. Verified progress saved for the next run."
                )
            self.result.pop("current_item", None)
            if epoch:
                self.state.set("sync_last_full_reconcile", time.time())
                self.state.set("sync_reconcile_started", 0)
            self.result.update(
                pending=len(pending), local_hashed_bytes=ownership.hashed_bytes
            )
            self.save()
            return pending
        finally:
            self.result.update(
                local_hashed_bytes=ownership.hashed_bytes,
                local_inventory_built=ownership.inventory_built,
                local_candidates_indexed=ownership.indexed_files,
                classification_seconds=round(time.monotonic() - started, 3),
            )
            try:
                self.checkpoint()
            finally:
                ownership.close()

    def admit(self, items: list[RemoteFile]) -> dict:
        admission = {
            "id": uuid.uuid4().hex,
            "created_at": now(),
            "inbox": str(self.inbox),
            "status": "staging",
            "files": [{**item.record(), "published": False} for item in items],
            "batch_summary": None,
        }
        self.state.set("sync_admission", admission)
        self.checkpoint()
        return admission

    def publish(self, admission: dict) -> None:
        self.result["phase"] = "publication"
        self.save()
        if admission["inbox"] != str(self.inbox):
            raise UsageError(
                "Unfinished batch belongs to a different inbox; resume using "
                "its recorded --inbox."
            )
        if admission["status"] == "processing":
            return
        staged: set[Path] = set()
        # Stage the entire remaining batch before any additional publication.
        try:
            if (
                sum(r["size"] for r in admission["files"] if not r["published"])
                > self.max_cache_bytes
            ):
                raise UsageError(
                    "Admitted batch exceeds --max-cache-bytes; increase the limit."
                )
            for row in admission["files"]:
                if row["published"]:
                    continue
                item = RemoteFile(
                    **{k: row[k] for k in ("identity", "version", "path", "size")}
                )
                path, digest = self.download(item, staged)
                row["sha256"] = digest
                staged.add(path)
            if admission["status"] == "staging":
                assert self.provider is not None
                for row in admission["files"]:
                    self.provider.validate(
                        RemoteFile(
                            **{
                                k: row[k]
                                for k in ("identity", "version", "path", "size")
                            }
                        )
                    )
        except Exception:
            # If an admission has never published anything, stale source snapshots
            # can be discarded safely; the next complete discovery reclassifies all.
            if not any(
                r["published"] or r.get("destination") for r in admission["files"]
            ):
                admission["status"] = "cancelled"
                self.state.set("sync_admission", admission)
                self.checkpoint()
            raise
        admission["status"] = "publishing"
        self.state.set("sync_admission", admission)
        self.checkpoint()
        for row in admission["files"]:
            self.check_time()
            if row["published"]:
                continue
            item = RemoteFile(
                **{k: row[k] for k in ("identity", "version", "path", "size")}
            )
            source = self.cached(item)
            target = destination_path(
                self.inbox / self.name, row.get("destination", item.path)
            )
            if not row.get("destination"):
                if target.exists() and (
                    not target.is_file() or file_hash(target) != row["sha256"]
                ):
                    suffix = hashlib.sha256(
                        f"{item.identity}:{item.version}".encode()
                    ).hexdigest()[:12]
                    target = target.with_name(
                        f"{target.stem} [{self.name}-{suffix}]{target.suffix}"
                    )
                row["destination"] = target.relative_to(
                    self.inbox / self.name
                ).as_posix()
                self.state.set("sync_admission", admission)
                self.checkpoint()
            target.parent.mkdir(parents=True, exist_ok=True)
            # A crash may have published the file before its journal checkpoint.
            if not target.exists():
                partial = target.with_name(f".rpg-sync-{admission['id']}.part")
                if partial.is_symlink():
                    raise UsageError("Unsafe publication partial path.")
                try:
                    with source.open("rb") as src, partial.open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                        dst.flush()
                        os.fsync(dst.fileno())
                    if file_hash(partial) != row["sha256"]:
                        raise RuntimeError("Staged bytes changed before publication.")
                    rename_no_replace(partial, target)
                finally:
                    partial.unlink(missing_ok=True)
            if not target.is_file() or file_hash(target) != row["sha256"]:
                raise UsageError(
                    "Recorded publication path has conflicting bytes; preserve "
                    "both files and resolve the collision."
                )
            descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            row["published"] = True
            self.result["published"] += 1
            self.state.set("sync_admission", admission)
            self.checkpoint()
            print(f"Imported {self.name}/{row['destination']}", flush=True)
        admission["status"] = "processing"
        self.state.set("sync_admission", admission)
        self.checkpoint()
