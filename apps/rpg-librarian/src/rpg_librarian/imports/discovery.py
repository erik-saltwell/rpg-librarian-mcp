from __future__ import annotations

import hashlib
import json
import time

from rpg_librarian_tools.onedrive import GraphError, OneDrive

from .state import State

CONTROL_FILES = {
    "catalog.json",
    "catalog.md",
    "boardgames.json",
    "boardgames_collection.csv",
    "email_hunt_findings.md",
}


def content_version(item: dict) -> str:
    # cTag describes content, while eTag also changes when a file is renamed.
    value = item.get("cTag") or json.dumps(
        [
            item.get("size"),
            item.get("lastModifiedDateTime"),
            item.get("file", {}).get("hashes"),
        ],
        sort_keys=True,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def discover(state: State, client: OneDrive, deadline: float) -> bool:
    """
    Checkpoint each delta page. Never select from an incomplete observation cycle."""
    generation = state.get("generation", 0)
    if not state.get("next") and state.get("reconciled_generation", 0) < generation:
        reconcile(state, client.root)
    url = state.get("next")
    if not url:
        generation += 1
        state.set("generation", generation)
        state.set("cycle_full", not bool(state.get("delta")))
        state.set("cycle_pages", 0)
        url = state.get("delta") or client.delta_url()
        state.set("next", url)
        state.db.commit()
    while time.monotonic() < deadline:
        try:
            payload = client.page(url)
        except GraphError as error:
            if error.status != 410:
                raise
            # Expired cursor: re-enumerate without discarding revisions or provenance.
            generation += 1
            state.set("generation", generation)
            state.set("cycle_full", True)
            state.set("next", client.delta_url())
            state.set("delta", None)
            state.db.commit()
            url = client.delta_url()
            continue
        with state.db:
            state.set("cycle_pages", state.get("cycle_pages", 0) + 1)
            for item in payload.get("value", []):
                identity = item["id"]
                previous = state.db.execute(
                    "SELECT data FROM remote WHERE id=?", (identity,)
                ).fetchone()
                # Graph tombstones/partial records may omit the old name and parent.
                merged = json.loads(previous[0]) if previous else {}
                merged.update(item)
                if "deleted" not in item:
                    merged.pop("deleted", None)
                kind = (
                    "folder"
                    if "folder" in merged
                    else "file"
                    if "file" in merged
                    else "other"
                )
                if "remoteItem" in merged:
                    kind = "shortcut"
                state.db.execute(
                    """
INSERT INTO remote(id,parent,name,kind,size,version,etag,data,deleted,generation)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET

parent=excluded.parent,name=excluded.name,kind=excluded.kind,size=excluded.size,
                    version=excluded.version,etag=excluded.etag,data=excluded.data,
                    deleted=excluded.deleted,generation=excluded.generation""",
                    (
                        identity,
                        merged.get("parentReference", {}).get("id"),
                        merged.get("name"),
                        kind,
                        merged.get("size", 0),
                        content_version(merged),
                        merged.get("eTag"),
                        json.dumps(merged),
                        int("deleted" in item),
                        generation,
                    ),
                )
            url = payload.get("@odata.nextLink")
            if url:
                state.set("next", url)
            else:
                delta = payload.get("@odata.deltaLink")
                if not delta:
                    raise RuntimeError(
                        "OneDrive delta page has no continuation checkpoint."
                    )
                if state.get("cycle_full"):
                    state.db.execute(
                        "UPDATE remote SET deleted=1 WHERE generation!=?", (generation,)
                    )
                state.set("delta", delta)
                state.set("next", None)
                state.set("baseline_complete", True)
        print("OneDrive metadata page saved.", flush=True)
        if not url:
            reconcile(state, client.root)
            return True
    return False


def reconcile(state: State, root: str) -> None:
    items = {r["id"]: dict(r) for r in state.db.execute("SELECT * FROM remote")}
    cache: dict[str, tuple[tuple[str, ...], str]] = {root: ((), root)}

    def path(identity: str, visited: set | None = None):
        if identity in cache:
            return cache[identity]
        visited = set() if visited is None else visited
        item = items.get(identity)
        if (
            identity in visited
            or not item
            or item["deleted"]
            or item["kind"] == "shortcut"
        ):
            return None
        visited.add(identity)
        parent = path(item["parent"], visited)
        name = item["name"]
        if (
            parent is None
            or not name
            or name in (".", "..")
            or any(c in name for c in ("/", "\\", "\0"))
        ):
            return None
        parts = (*parent[0], name)
        result = (parts, identity if len(parts) == 1 else parent[1])
        cache[identity] = result
        return result

    with state.db:
        state.db.execute("UPDATE remote SET eligible=0")
        for item in items.values():
            resolved = path(item["id"])
            if resolved is None:
                continue
            parts, group_id = resolved
            if not parts:
                continue
            eligible = item["kind"] == "file" and not any(
                p.startswith("_") for p in parts[:-1]
            )
            eligible = (
                eligible
                and parts[-1].casefold() != "_index.md"
                and not (len(parts) == 1 and parts[0].casefold() in CONTROL_FILES)
            )
            relative = "/".join(parts)
            # Root-level files form their own complete groups.
            group_path = parts[0] if len(parts) > 1 else ""
            state.db.execute(
                "UPDATE remote SET path=?,group_id=?,eligible=? WHERE id=?",
                (relative, group_id, int(eligible), item["id"]),
            )
            if not eligible:
                continue
            prior = state.db.execute(
                "SELECT id FROM folder_group WHERE id=?", (group_id,)
            ).fetchone()
            state.db.execute(
                (
                    "INSERT INTO folder_group(id,path,fresh) "
                    "VALUES(?,?,?) ON "
                    "CONFLICT(id) DO UPDATE SET "
                    "path=excluded.path"
                ),
                (group_id, group_path, int(state.get("completed_cycles", 0) > 0)),
            )
            existing = state.db.execute(
                "SELECT id FROM revision WHERE remote_id=? AND version=?",
                (item["id"], item["version"]),
            ).fetchone()
            state.db.execute(
                (
                    "INSERT OR IGNORE INTO "
                    "revision(remote_id,version,group_id,sour"
                    "ce_path,size) "
                    "VALUES(?,?,?,?,?)"
                ),
                (item["id"], item["version"], group_id, relative, item["size"]),
            )
            # Keep the original imported source path on the revision,
            # current path on remote.
            if not existing and prior:
                state.db.execute(
                    "UPDATE folder_group SET stage='queued',fresh=? WHERE id=?",
                    (int(state.get("completed_cycles", 0) > 0), group_id),
                )
            state.db.execute(
                (
                    "UPDATE revision SET group_id=? WHERE "
                    "remote_id=? AND "
                    "version=? AND status IN "
                    "('pending','cancelled')"
                ),
                (group_id, item["id"], item["version"]),
            )
        state.db.execute("""
UPDATE revision SET status='cancelled' WHERE status='pending' AND NOT EXISTS
            (SELECT 1 FROM remote WHERE remote.id=revision.remote_id AND
remote.version=revision.version AND remote.eligible=1 AND remote.deleted=0)""")
        state.db.execute("""
UPDATE revision SET status='pending' WHERE status='cancelled' AND EXISTS
            (SELECT 1 FROM remote WHERE remote.id=revision.remote_id AND
remote.version=revision.version AND remote.eligible=1 AND remote.deleted=0)""")
        state.db.execute(
            "UPDATE review SET resolved=1 WHERE subject IN "
            "(SELECT 'transfer:' || id FROM revision WHERE status='cancelled')"
        )
        state.set("completed_cycles", state.get("completed_cycles", 0) + 1)
        state.set("reconciled_generation", state.get("generation", 0))
