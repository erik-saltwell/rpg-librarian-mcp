from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path, PurePosixPath

from rpg_librarian_tools.onedrive import OneDrive

from ..services.file_moves import rename_no_replace
from .discovery import content_version
from .matching import Matcher
from .state import State


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def destination_path(inbox: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or PurePosixPath(relative).is_absolute()
        or any(p in (".", "..") or "\\" in p or "\0" in p for p in parts)
    ):
        raise ValueError("Unsafe source filename/path.")
    path = inbox.joinpath(*parts)
    if not path.resolve().is_relative_to(inbox.resolve()):
        raise ValueError("Source destination escapes the importer inbox.")
    if any(inbox.joinpath(*parts[:i]).is_symlink() for i in range(len(parts) + 1)):
        raise ValueError("Importer destination contains a symbolic link.")
    return path


def transfer(
    state: State, client: OneDrive, matcher: Matcher, inbox: Path, args, deadline: float
) -> dict:
    summary = {
        "downloaded_files": 0,
        "attempted_files": 0,
        "reserved_bytes": 0,
        "downloaded_bytes": 0,
        "already_owned": 0,
        "errors": 0,
        "stop": None,
    }

    def evidence(row: dict) -> str:
        return json.dumps(
            {
                key: row.get(key)
                for key in (
                    "id",
                    "root_id",
                    "relative_path",
                    "size_bytes",
                    "mtime",
                    "sha256",
                    "line_id",
                )
            },
            sort_keys=True,
        )

    checked_folders = set()

    def check_ancestry(metadata: dict, recorded: dict) -> None:
        if metadata.get("parentReference", {}).get("id") != recorded.get(
            "parentReference", {}
        ).get("id") or metadata.get("name") != recorded.get("name"):
            raise RuntimeError(
                "Source moved/renamed since discovery; retry after discovery."
            )
        parent = metadata.get("parentReference", {}).get("id")
        visited = set()
        while parent and parent != client.root and parent not in checked_folders:
            if parent in visited:
                raise RuntimeError("Source ancestry has a cycle.")
            visited.add(parent)
            stored = state.db.execute(
                "SELECT data FROM remote WHERE id=?", (parent,)
            ).fetchone()
            if stored is None:
                raise RuntimeError("Source ancestry is incomplete; finish discovery.")
            actual, expected = client.metadata(parent), json.loads(stored[0])
            if actual.get("name", "").startswith("_"):
                raise RuntimeError("Source is now under an excluded underscore folder.")
            if actual.get("name") != expected.get("name") or actual.get(
                "parentReference", {}
            ).get("id") != expected.get("parentReference", {}).get("id"):
                raise RuntimeError(
                    "Source folder moved/renamed; retry after discovery."
                )
            parent = actual.get("parentReference", {}).get("id")
        if not parent:
            raise RuntimeError(
                "Source is no longer inside the configured shared folder."
            )

        checked_folders.update(visited)

    # Reconcile publication before filtering by current remote versions. A crash
    # followed by a remote edit/delete must not strand an older revision forever.
    recovering = state.db.execute(
        "SELECT * FROM revision WHERE status='publishing'"
    ).fetchall()
    for record in recovering:
        row = dict(record)
        target = (
            destination_path(inbox, row["destination"]) if row["destination"] else None
        )
        if (
            target
            and target.is_file()
            and row["sha256"]
            and file_hash(target) == row["sha256"]
        ):
            state.db.execute(
                "UPDATE revision SET status='published',error=NULL,retry_at=0 "
                "WHERE id=?",
                (row["id"],),
            )
        elif not state.db.execute(
            "SELECT 1 FROM remote WHERE id=? AND version=? "
            "AND eligible=1 AND deleted=0",
            (row["remote_id"], row["version"]),
        ).fetchone():
            state.db.execute(
                "UPDATE revision SET status='cancelled' WHERE id=?", (row["id"],)
            )
    state.db.commit()
    groups = state.db.execute("""
SELECT * FROM folder_group WHERE stage IN ('queued','transferring')
        ORDER BY selected DESC,fresh DESC,path COLLATE NOCASE,id""").fetchall()
    for group in groups:
        if args.folder is not None and group["path"] != args.folder:
            continue
        if time.monotonic() >= deadline:
            summary["stop"] = "time budget"
            break
        state.db.execute(
            (
                "UPDATE folder_group SET selected=1,fresh=0,stage='transferring' "
                "WHERE id=?"
            ),
            (group["id"],),
        )
        state.db.commit()
        # The entire group stays queued: limits never truncate its membership.
        rows = state.db.execute(
            """
SELECT v.*,r.path current_path,r.name,r.etag,r.data FROM revision v
            JOIN remote r ON r.id=v.remote_id AND r.version=v.version
            WHERE v.group_id=? AND v.status IN ('pending','publishing') AND
r.eligible=1 AND r.deleted=0
            ORDER BY r.path COLLATE NOCASE""",
            (group["id"],),
        ).fetchall()
        for record in rows:
            row = dict(record)
            if row["retry_at"] > time.time():
                continue
            if (
                time.monotonic() >= deadline
                or summary["attempted_files"] >= args.max_files
            ):
                summary["stop"] = "time/file budget"
                return summary
            item = {
                "path": row["current_path"],
                "name": row["name"],
                "size": row["size"],
            }
            try:
                if row["status"] != "publishing":
                    # Changed remote content must be checked by
                    # bytes, not silently skipped on its old name.
                    previous = state.db.execute(
                        (
                            "SELECT 1 FROM revision WHERE remote_id=?"
                            " AND version!=? AND "
                            "status IN "
                            "('owned','published','processed')"
                        ),
                        (row["remote_id"], row["version"]),
                    ).fetchone()
                    method, local = (
                        matcher.match(item) if not previous else (None, None)
                    )
                    if local:
                        state.db.execute(
                            (
                                "UPDATE revision SET "
                                "status='owned',method=?,matching_file_id"
                                "=?,match_evidence=? WHERE id=?"
                            ),
                            (method, local["id"], evidence(local), row["id"]),
                        )
                        state.db.commit()
                        state.resolve(f"transfer:{row['id']}")
                        summary["already_owned"] += 1
                        continue
                if summary["reserved_bytes"] + row["size"] > args.max_bytes and (
                    not args.allow_oversized or summary["attempted_files"]
                ):
                    summary["stop"] = (
                        "byte budget (use --allow-oversized for a"
                        " file larger than "
                        "the limit)"
                    )
                    return summary
                # Reconcile a crash after publication using the journal's expected hash.
                relative = row["destination"] or row["current_path"]
                destination = destination_path(inbox, relative)
                partial = destination.with_name(".brendan-" + str(row["id"]) + ".part")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if (
                    row["status"] == "publishing"
                    and row["sha256"]
                    and destination.is_file()
                    and file_hash(destination) == row["sha256"]
                ):
                    state.db.execute(
                        (
                            "UPDATE revision SET "
                            "status='published',error=NULL,retry_at=0"
                            " WHERE id=?"
                        ),
                        (row["id"],),
                    )
                    state.db.commit()
                    continue
                metadata = client.metadata(row["remote_id"])
                check_ancestry(metadata, json.loads(row["data"]))
                if (
                    content_version(metadata) != row["version"]
                    or metadata.get("size") != row["size"]
                ):
                    raise RuntimeError("Remote content changed; run discovery again.")
                partial.unlink(missing_ok=True)
                summary["attempted_files"] += 1
                summary["reserved_bytes"] += row["size"]
                digest = client.download(row["remote_id"], partial, row["size"])
                summary["downloaded_files"] += 1
                summary["downloaded_bytes"] += row["size"]
                if content_version(client.metadata(row["remote_id"])) != row["version"]:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError("Remote content changed during transfer.")
                exact = matcher.exact(digest)
                if exact:
                    partial.unlink(missing_ok=True)
                    state.db.execute(
                        (
                            "UPDATE revision SET "
                            "status='owned',method='sha256',sha256=?,"
                            "matching_file_id=?,match_evidence=?,error=NULL WHERE id=?"
                        ),
                        (digest, exact["id"], evidence(exact), row["id"]),
                    )
                    state.db.commit()
                    state.resolve(f"transfer:{row['id']}")
                    summary["already_owned"] += 1
                    continue
                # A new revision or conflicting local file receives
                # its own name, never an overwrite.
                if destination.exists():
                    suffix = hashlib.sha256(
                        f"{row['remote_id']}:{row['version']}".encode()
                    ).hexdigest()[:12]
                    destination = destination.with_name(
                        f"{destination.stem} [brendan-{suffix}]{destination.suffix}"
                    )
                relative = destination.relative_to(inbox).as_posix()
                state.db.execute(
                    (
                        "UPDATE revision SET "
                        "status='publishing',sha256=?,destination"
                        "=? WHERE id=?"
                    ),
                    (digest, relative, row["id"]),
                )
                state.db.commit()
                rename_no_replace(partial, destination)
                state.db.execute(
                    (
                        "UPDATE revision SET "
                        "status='published',error=NULL,retry_at=0"
                        " WHERE id=?"
                    ),
                    (row["id"],),
                )
                state.db.commit()
                state.resolve(f"transfer:{row['id']}")
                print(f"Imported {relative}", flush=True)
            except Exception as error:
                summary["errors"] += 1
                # Do not persist requests' sensitive redirect URLs or bearer headers.
                reason = (
                    str(error)
                    if isinstance(error, (RuntimeError, ValueError, TimeoutError))
                    else type(error).__name__
                )
                state.failure(row["id"], reason)
                print(
                    f"Transfer deferred: {row['current_path']} "
                    f"({type(error).__name__}).",
                    flush=True,
                )
        pending = state.db.execute(
            (
                "SELECT count(*) FROM revision WHERE "
                "group_id=? AND status IN"
                " ('pending','publishing')"
            ),
            (group["id"],),
        ).fetchone()[0]
        if not pending:
            state.db.execute(
                "UPDATE folder_group SET stage='ready' WHERE id=?", (group["id"],)
            )
            state.db.commit()
    return summary
