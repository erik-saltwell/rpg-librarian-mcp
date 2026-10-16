"""CLI entry points for the manually run Brendan importer."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from sqlmodel import select

from rpg_librarian_tools.onedrive import GraphError, OneDrive

from ..db import session_scope
from ..errors import UsageError
from ..imports.auth import token
from ..imports.config import Config
from ..imports.discovery import discover
from ..imports.matching import Matcher
from ..imports.notifications import export_reviews, notify
from ..imports.processing import process, reconcile_reviews
from ..imports.state import State, job_lock
from ..imports.transfer import transfer
from ..model import Root, RootKind
from ..observability import log_call_fields


def register(state: State, catalog: Path, inbox: Path | None) -> None:
    config = Config.load()
    with session_scope(catalog) as session:
        roots = list(session.exec(select(Root)).all())
        staging = [r for r in roots if r.kind is RootKind.staging]
        if inbox is None:
            if len(staging) != 1:
                raise UsageError("Specify --inbox below an existing staging root.")
            inbox = Path(staging[0].path) / "brendan"
        inbox = inbox.expanduser().absolute()
        parents = [
            r
            for r in staging
            if inbox.is_relative_to(Path(r.path)) and inbox != Path(r.path)
        ]
        if len(parents) != 1:
            raise UsageError(
                "The importer inbox must be below one "
                "existing staging root, "
                "not a new root."
            )
        root = parents[0]
        relative = inbox.relative_to(Path(root.path))
        if inbox.resolve() != inbox or any(
            p.startswith((".", "_")) for p in relative.parts
        ):
            raise UsageError(
                "Use an inbox path without symlinks, "
                "hidden or underscore-"
                "prefixed components."
            )
        if not Path(root.path).is_dir():
            raise UsageError("The staging root is not mounted/reachable.")
        previous = state.get("source")
        identity = {"drive": config.drive, "root": config.root, "inbox": str(inbox)}
        if previous and previous != identity:
            raise UsageError(
                "The journal already tracks another "
                "source/destination. Do "
                "not change IDs or inbox in place."
            )
        inbox.mkdir(parents=True, exist_ok=True)
        state.set("source", identity)
        state.set("root_id", root.id)
        state.set("prefix", relative.as_posix())
        state.db.commit()
    print(f"Registered Brendan importer inbox: {inbox}")


def source(args: argparse.Namespace, catalog: Path) -> int:
    if args.name != "brendan":
        raise UsageError("The supported source is brendan.")
    if args.action == "auth":
        token(Config.load(), interactive=True)
        print("Microsoft authorization is ready; token cache saved privately.")
        return 0
    state = State(catalog, args.name)
    try:
        with job_lock(state):
            if args.action == "add":
                register(state, catalog, args.inbox)
            else:
                config = Config.load()
                client = OneDrive(
                    token(config), config.drive, config.root, time.monotonic() + 120
                )
                try:
                    metadata = client.metadata(config.root)
                    if "folder" not in metadata:
                        raise UsageError("Configured OneDrive root is not a folder.")
                    client.page(client.delta_url())
                finally:
                    client.close()
                print(
                    "Microsoft cached sign-in, shared-folder "
                    "metadata and delta "
                    "access: OK"
                )
                if state.get("source"):
                    inbox = Path(state.get("source")["inbox"])
                    print(
                        f"Inbox reachable: {inbox.is_dir()}; free bytes: "
                        f"{shutil.disk_usage(inbox).free if inbox.is_dir() else 0}"
                    )
                else:
                    print("Source not registered. Run import-source add brendan.")
                print(f"Headless filing CLI available: {bool(shutil.which('claude'))}")
    except (GraphError, ConnectionError, TimeoutError) as error:
        raise UsageError(str(error)) from None
    finally:
        state.close()
    return 0


def status(args: argparse.Namespace, catalog: Path) -> int:
    state = State(catalog, args.name)
    try:
        report = {
            "registered": bool(state.get("source")),
            "baseline_complete": state.get("baseline_complete", False),
            "discovery_in_progress": bool(state.get("next")),
            "remote_eligible_files": state.db.execute(
                "SELECT count(*) FROM remote WHERE eligible=1 AND deleted=0"
            ).fetchone()[0],
            "revisions": dict(
                state.db.execute("SELECT status,count(*) FROM revision GROUP BY status")
            ),
            "folder_groups": dict(
                state.db.execute(
                    "SELECT stage,count(*) FROM folder_group GROUP BY stage"
                )
            ),
            "unfinished_selected_folders": [
                dict(r)
                for r in state.db.execute(
                    "SELECT path,stage FROM folder_group "
                    "WHERE selected=1 AND "
                    "stage!='complete' ORDER BY path"
                )
            ],
            "pending_bytes": state.db.execute(
                "SELECT COALESCE(sum(size),0) FROM revision WHERE status='pending'"
            ).fetchone()[0],
            "open_reviews": state.db.execute(
                "SELECT count(*) FROM review WHERE resolved=0"
            ).fetchone()[0],
            "mail_pending": state.db.execute(
                "SELECT count(*) FROM digest WHERE status='pending'"
            ).fetchone()[0],
            "last_run": None,
        }
        run = state.db.execute(
            "SELECT started,finished,outcome,summary FROM run ORDER BY id DESC LIMIT 1"
        ).fetchone()
        report["last_run"] = dict(run) if run else None
        print(json.dumps(report, indent=2))
    finally:
        state.close()
    return 0


def reviews(args: argparse.Namespace, catalog: Path) -> int:
    state = State(catalog, args.name)
    try:
        with job_lock(state):
            # Refresh flags without treating exports as repeated failed run attempts.
            reconcile_reviews(state, catalog, count_errors=False)
            report = export_reviews(state)
            if args.out:
                shutil.copyfile(report, args.out)
                report = args.out
            print(report)
    finally:
        state.close()
    return 0


def resolve(args: argparse.Namespace, catalog: Path) -> int:
    state = State(catalog, "brendan")
    try:
        with job_lock(state):
            if args.subject.startswith(("entry:", "error:")):
                raise UsageError(
                    "Resolve catalog reviews/errors with "
                    "update-product or the "
                    "relevant processing command."
                )
            if not state.db.execute(
                "SELECT 1 FROM review WHERE subject=?", (args.subject,)
            ).fetchone():
                raise UsageError("No such importer review.")
            state.resolve(args.subject)
            print(
                "Importer review resolved. If its cause "
                "persists, a later run"
                " will reopen it."
            )
    finally:
        state.close()
    return 0


def run(args: argparse.Namespace, catalog: Path) -> int:
    if min(args.max_files, args.max_bytes, args.max_seconds, args.max_entries) < 1:
        raise UsageError("Run limits must be positive.")
    if args.discover_only and args.process_only:
        raise UsageError("Choose discover-only or process-only, not both.")
    state = State(catalog, args.name)
    client = None
    try:
        with job_lock(state):
            if not state.get("source"):
                register(state, catalog, args.inbox)
            identity = state.get("source")
            inbox = Path(identity["inbox"])
            if not inbox.is_dir():
                raise UsageError(
                    "Importer inbox is unreachable; mount the share before running."
                )
            deadline = time.monotonic() + args.max_seconds
            # Any interrupted previous run is historical, not an active lease.
            state.db.execute(
                "UPDATE run SET "
                "finished=CURRENT_TIMESTAMP,outcome='inte"
                "rrupted' WHERE "
                "finished IS NULL"
            )
            run_id = state.db.execute("INSERT INTO run DEFAULT VALUES").lastrowid
            state.db.commit()
            result = {"source": args.name, "run_id": run_id}
            operational_failure = False
            remote_ready = False
            if not args.process_only:
                try:
                    config = Config.load()
                    if (
                        config.drive != identity["drive"]
                        or config.root != identity["root"]
                    ):
                        raise UsageError(
                            "Source IDs changed; restore the "
                            "registered .env configuration."
                        )
                    client = OneDrive(
                        token(config), config.drive, config.root, deadline
                    )
                    remote_ready = discover(
                        state,
                        client,
                        min(
                            deadline, time.monotonic() + min(600, args.max_seconds / 3)
                        ),
                    )
                    state.resolve("source:access")
                except (UsageError, GraphError, ConnectionError, TimeoutError) as error:
                    operational_failure = True
                    result["remote_error"] = str(error)
                    if isinstance(error, UsageError) or (
                        isinstance(error, GraphError)
                        and error.status in (401, 403, 404)
                    ):
                        state.review(
                            "source:access",
                            str(error) + " Check Microsoft authorization and "
                            "shared-folder access.",
                        )
                    print(
                        f"Remote discovery paused ({type(error).__name__}); "
                        "saved local work can continue.",
                        flush=True,
                    )
            if (
                args.folder is not None
                and remote_ready
                and not state.db.execute(
                    "SELECT 1 FROM folder_group WHERE path=?", (args.folder,)
                ).fetchone()
            ):
                raise UsageError(
                    "That top-level folder has no eligible "
                    "files in the source "
                    "inventory."
                )
            if remote_ready and not args.discover_only and client is not None:
                remote = [
                    dict(r)
                    for r in state.db.execute(
                        "SELECT * FROM remote WHERE eligible=1 AND deleted=0"
                    )
                ]
                seed = None
                # The root catalog is optional context, never the
                # authoritative inventory.
                catalog_item = state.db.execute(
                    (
                        "SELECT id,etag,size FROM remote WHERE "
                        "parent=? AND "
                        "name='catalog.json' AND deleted=0"
                    ),
                    (identity["root"],),
                ).fetchone()
                seed_path = state.directory / "brendan-catalog.json"
                if catalog_item and catalog_item["size"] <= 5 * 1024 * 1024:
                    try:
                        if (
                            state.get("catalog_etag") != catalog_item["etag"]
                            or not seed_path.exists()
                        ):
                            temp = seed_path.with_suffix(".part")
                            client.download(
                                catalog_item["id"], temp, catalog_item["size"]
                            )
                            candidate = json.loads(temp.read_text())
                            if not isinstance(candidate, dict) or not isinstance(
                                candidate.get("items"), list
                            ):
                                raise ValueError("Invalid optional source catalog.")
                            temp.replace(seed_path)
                            seed_path.chmod(0o600)
                            state.set("catalog_etag", catalog_item["etag"])
                            state.db.commit()
                        seed = json.loads(seed_path.read_text())
                    except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                        print(
                            "Optional source catalog unavailable; "
                            "matching will use "
                            "current filenames."
                        )
                matcher = Matcher(catalog, remote, seed)
                try:
                    result.update(
                        transfer(state, client, matcher, inbox, args, deadline)
                    )
                finally:
                    matcher.close()
            # Partial observation cycles can contain unseen additions to a folder.
            # Keep the complete-folder guarantee by waiting for their checkpoint.
            if (
                not args.no_process
                and not args.discover_only
                and (
                    not state.get("next")
                    or (
                        state.get("cycle_pages", 0) == 0
                        and state.get("baseline_complete")
                    )
                )
            ):
                processing_result = process(state, catalog, args, deadline)
                result.update(processing_result)
                operational_failure |= bool(
                    processing_result["shared_processing_failure"]
                )
            if not args.discover_only:
                try:
                    result["emailed_reviews"] = notify(state, enabled=not args.no_email)
                except RuntimeError as error:
                    operational_failure = True
                    result["mail_error"] = str(error)
                    print(str(error))
            result["discovery_complete"] = remote_ready
            with state.db:
                state.db.execute(
                    (
                        "UPDATE run SET "
                        "finished=CURRENT_TIMESTAMP,outcome=?,sum"
                        "mary=? WHERE id=?"
                    ),
                    (
                        "operational_failure"
                        if operational_failure
                        else "bounded_complete",
                        json.dumps(result),
                        run_id,
                    ),
                )
            log_call_fields(**result)
            print(json.dumps(result, indent=2))
            return int(operational_failure)
    finally:
        if client is not None:
            client.close()
        state.close()


def retired_run(args: argparse.Namespace, catalog: Path) -> int:
    raise UsageError(
        "import-run is retired. Use sync-sources --source brendan --catalog "
        f"{catalog} --inbox <registered staging root> --max-new-files 100. "
        "The threshold applies to the entire pending source, not a transfer budget. "
        "Existing source history is preserved and adopted automatically."
    )
