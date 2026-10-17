"""Serial source lifecycle under one catalog orchestration lock."""

from __future__ import annotations

import json
import signal
import time
import traceback
import uuid
from pathlib import Path

from sqlmodel import select

from ..batch.notifications import notify as notify_batch
from ..batch.processes import stop_abandoned
from ..batch.records import Run, now, write_json
from ..batch.runner import _run_batch_locked
from ..db import session_scope
from ..errors import UsageError
from ..imports.state import State
from ..infrastructure.job_lock import catalog_job_lock
from ..model import Root, RootKind
from ..services.review_backlog import collect
from .ingestion import Ingestion
from .notifications import failures, manual_required
from .providers import open_provider
from .registry import Registry, valid_name


class Interrupted(KeyboardInterrupt):
    def __init__(self, exit_code: int):
        self.exit_code = exit_code


def validate_inbox(catalog: Path, inbox: Path) -> None:
    if inbox.resolve() != inbox or not inbox.is_dir():
        raise UsageError("--inbox must be a reachable staging root without symlinks.")
    with session_scope(catalog) as session:
        roots = session.exec(select(Root)).all()
        registered = any(
            r.kind == RootKind.staging and Path(r.path) == inbox for r in roots
        )
        library_reachable = any(
            r.kind == RootKind.library and Path(r.path).is_dir() for r in roots
        )
    if not registered:
        raise UsageError(
            "--inbox must be an existing registered staging root; use add-source first."
        )
    if not library_reachable:
        raise UsageError("The catalog needs a reachable library root before syncing.")


def recover(catalog: Path, run_id: str) -> None:
    for path in (catalog.parent / "logs" / "sync-sources").glob("*/summary.json"):
        if path.parent.name == run_id:
            continue
        try:
            record = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if record.get("catalog") == str(catalog) and record.get("finished_at") is None:
            record.update(outcome="interrupted", finished_at=now(), recovered_by=run_id)
            for source in record.get("sources", []):
                if source.get("outcome") == "running":
                    source.update(outcome="interrupted", finished_at=now())
            if record.get("notification", {}).get("status") == "pending":
                record["notification"] = {
                    "status": "unknown",
                    "reason": "delivery_interrupted",
                }
            elif record.get("notification", {}).get("status") == "not_evaluated":
                record["notification"] = {
                    "status": "skipped",
                    "reason": "parent_interrupted",
                }
            write_json(path, record)
    for path in (catalog.parent / "logs" / "process-batch").glob("*/summary.json"):
        try:
            record = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if record.get("catalog") == str(catalog) and record.get("finished_at") is None:
            stop_abandoned(record["run_id"])
            record.update(outcome="interrupted", finished_at=now(), recovered_by=run_id)
            for stage in record.get("stages", []):
                if stage["outcome"] == "running":
                    stage.update(outcome="interrupted", finished_at=now())
            record["notification"] = {
                **record.get("notification", {}),
                "status": "unknown"
                if record.get("notification", {}).get("status") == "pending"
                else "skipped",
                "reason": "parent_interrupted",
            }
            write_json(path, record)


def process_source(
    registry: Registry, name: str, source: dict, inbox: Path, args, result: dict, save
) -> None:
    valid_name(name)
    state = State(registry.catalog, name)
    provider = None
    deadline = time.monotonic() + args.max_seconds
    try:
        identity = {
            k: v for k, v in source.items() if k not in {"enabled", "legacy_inbox"}
        }
        legacy_identity = state.get("source")
        if (
            legacy_identity
            and source["provider"] == "onedrive"
            and (
                legacy_identity["drive"] != source["drive"]
                or legacy_identity["root"] != source["folder"]
            )
        ):
            raise UsageError("Registered source differs from legacy journal identity.")
        if state.get("sync_identity") not in (None, identity):
            raise UsageError(
                "Source identity differs from the existing journal; use a "
                "new source name."
            )
        state.set("sync_identity", identity)
        if source.get("legacy_inbox") and not state.get("sync_legacy_migrated"):
            previous_inbox = Path(source["legacy_inbox"])
            legacy = state.db.execute(
                "SELECT * FROM revision WHERE status IN ('published','publishing') "
                "AND sha256 IS NOT NULL"
            ).fetchall()
            # Published legacy work was already admitted by the old command.
            # Preserve its handoff even though local hash exclusion now sees it.
            published = [
                row
                for row in legacy
                if row["status"] == "published"
                or (
                    row["destination"]
                    and (previous_inbox / row["destination"]).is_file()
                )
            ]
            if published:
                if previous_inbox != inbox / name:
                    raise UsageError(
                        "Legacy unfinished work uses another inbox. Resume with "
                        f"--inbox {previous_inbox.parent} before changing destinations."
                    )
                state.set(
                    "sync_admission",
                    {
                        "id": "legacy-" + uuid.uuid4().hex,
                        "created_at": now(),
                        "inbox": str(inbox),
                        "status": "processing",
                        "batch_summary": None,
                        "files": [
                            {
                                "identity": row["remote_id"],
                                "version": row["version"],
                                "path": row["source_path"],
                                "size": row["size"],
                                "sha256": row["sha256"],
                                "published": True,
                                "destination": row["destination"],
                            }
                            for row in published
                        ],
                    },
                )
            state.set("sync_legacy_migrated", True)
        state.db.commit()
        admission = state.get("sync_admission")
        # A completed receipt can be reconciled without network/sign-in on recovery.
        if (
            admission
            and admission["status"] == "processing"
            and admission.get("batch_summary")
        ):
            try:
                previous_batch = Run.load(Path(admission["batch_summary"]))
            except (OSError, ValueError):
                previous_batch = None
            if (
                previous_batch is not None
                and previous_batch.data.get("outcome") == "completed"
            ):
                result.update(resumed=True, batch_summary=str(previous_batch.path))
                notification = previous_batch.data.get("notification", {})
                if notification.get("status") == "failed":
                    with session_scope(registry.catalog, migrate=False) as session:
                        backlog = collect(session)
                    previous_batch.data["backlog"] = {
                        key: backlog[key] for key in ("total", "counts")
                    }
                    if not notify_batch(previous_batch):
                        raise RuntimeError(
                            "Completed processing; review email retry failed."
                        )
                elif notification.get("status") == "pending":
                    previous_batch.data["notification"] = {
                        **notification,
                        "status": "unknown",
                        "reason": "delivery_interrupted",
                    }
                    previous_batch.save()
                admission["status"] = "completed"
                state.set("sync_admission", admission)
                state.db.commit()
                result.update(
                    outcome="completed", backlog=previous_batch.data.get("backlog")
                )
                save()
                return
        if not (admission and admission["status"] == "processing"):
            provider = open_provider(registry, source, state, deadline)
        ingestion = Ingestion(
            name, state, provider, inbox, args.max_cache_bytes, deadline, result, save
        )
        if admission and admission["status"] not in {"completed", "cancelled"}:
            result["resumed"] = True
            finish(ingestion, admission, registry.catalog, result, save)
            # Finish the explicitly recorded batch only, then consider fresh source
            # content on the next scheduled run; no second batch for this source now.
            return
        assert provider is not None
        items = provider.observe()
        pending = ingestion.classify(registry.catalog, items)
        if not pending:
            state.set("sync_manual_notice", {})
            state.db.commit()
            result["outcome"] = "idle"
        elif len(pending) > args.max_new_files:
            result.update(
                outcome="manual_required", manifest=[i.record() for i in pending]
            )
            if not manual_required(
                state, name, pending, args.max_new_files, result, args.receipt, save
            ):
                raise RuntimeError(
                    "Manual-import notification failed; check SMTP settings and rerun."
                )
        else:
            state.set("sync_manual_notice", {})
            state.db.commit()
            admission = ingestion.admit(pending)
            finish(ingestion, admission, registry.catalog, result, save)
    finally:
        if provider is not None:
            provider.close()
        state.close()


def finish(
    ingestion: Ingestion, admission: dict, catalog: Path, result: dict, save
) -> None:
    ingestion.publish(admission)
    result["admission_id"] = admission["id"]

    def prepared(batch):
        admission["batch_summary"] = str(batch.path)
        result["batch_summary"] = str(batch.path)
        ingestion.state.set("sync_admission", admission)
        ingestion.checkpoint()

    code = _run_batch_locked(
        catalog, ingestion.inbox, source=ingestion.name, prepared=prepared
    )
    batch = json.loads(Path(admission["batch_summary"]).read_text())
    result["backlog"] = batch.get("backlog")
    if code in (130, 143):
        raise Interrupted(code)
    if code:
        failed = [
            s["name"]
            for s in batch["stages"]
            if s["outcome"] not in {"completed", "skipped"}
        ]
        raise RuntimeError(
            "Processing incomplete"
            + (f" ({', '.join(failed)})" if failed else " or notification failed")
            + "; see linked stage logs."
        )
    admission.update(status="completed", finished_at=now())
    ingestion.state.set("sync_admission", admission)
    ingestion.checkpoint()
    result["outcome"] = "completed"
    save()


def run(args, catalog: Path) -> int:
    catalog = catalog.resolve()
    if args.max_new_files < 0 or args.max_seconds <= 0 or args.max_cache_bytes <= 0:
        raise UsageError(
            "Threshold must be nonnegative; time and cache limits must be positive."
        )
    run_id = (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:12]
    )
    directory = catalog.parent / "logs" / "sync-sources" / run_id
    directory.mkdir(mode=0o700, parents=True)
    path = directory / "summary.json"
    args.receipt = str(path)
    inbox = args.inbox.expanduser().absolute()
    run_record = {
        "version": 1,
        "run_id": run_id,
        "catalog": str(catalog),
        "inbox": str(inbox),
        "started_at": now(),
        "finished_at": None,
        "outcome": "running",
        "sources": [],
        "notification": {"status": "not_evaluated"},
    }

    def save():
        write_json(path, run_record)

    save()
    previous = signal.getsignal(signal.SIGTERM)
    terminated = False

    def terminate(signum, frame):
        nonlocal terminated
        terminated = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    code = 1
    try:
        with catalog_job_lock(catalog):
            recover(catalog, run_id)
            registry = Registry(catalog)
            registry.migrate_brendan()
            validate_inbox(catalog, inbox)
            selected = args.source or sorted(
                name
                for name, source in registry.data["sources"].items()
                if source["enabled"]
            )
            selected = list(dict.fromkeys(selected))
            unknown = set(selected) - registry.data["sources"].keys()
            if unknown:
                raise UsageError("Unknown source(s): " + ", ".join(sorted(unknown)))
            for name in selected:
                result = {
                    "name": name,
                    "outcome": "running",
                    "started_at": now(),
                    "threshold": args.max_new_files,
                    "downloaded_files": 0,
                    "downloaded_bytes": 0,
                    "published": 0,
                }
                run_record["sources"].append(result)
                save()
                print(f"Source: {name}", flush=True)
                try:
                    process_source(
                        registry,
                        name,
                        registry.data["sources"][name],
                        inbox,
                        args,
                        result,
                        save,
                    )
                except Exception as error:
                    result.update(outcome="failed", error_type=type(error).__name__)
                    # Frame locations without locals, tokens or raw HTTP messages.
                    result["traceback"] = traceback.format_tb(error.__traceback__)
                    result["error"] = (
                        str(error)[:1000]
                        if isinstance(
                            error,
                            (UsageError, RuntimeError, TimeoutError, ConnectionError),
                        )
                        else type(error).__name__
                    )
                    print(
                        f"Source failed: {name} ({result['error_type']}); continuing.",
                        flush=True,
                    )
                finally:
                    result["finished_at"] = now()
                    save()
            run_record["outcome"] = (
                "failed"
                if any(r["outcome"] == "failed" for r in run_record["sources"])
                else "completed"
            )
            delivered = failures(run_record, str(path), save)
            code = 0 if run_record["outcome"] == "completed" and delivered else 1
    except KeyboardInterrupt as error:
        run_record["outcome"] = "interrupted"
        for result in run_record["sources"]:
            if result["outcome"] == "running":
                result.update(
                    outcome="failed",
                    error_type="Interrupted",
                    error="Interrupted; unfinished admitted work will resume on the "
                    "next run.",
                )
        if run_record["notification"].get("status") == "pending":
            run_record["notification"] = {
                "status": "unknown",
                "reason": "delivery_interrupted",
            }
            save()
        else:
            failures(run_record, str(path), save)
        code = getattr(error, "exit_code", 143 if terminated else 130)
    except Exception as error:
        run_record["outcome"] = "failed"
        run_record["sources"].append(
            {
                "name": "sync setup",
                "outcome": "failed",
                "error_type": type(error).__name__,
                "error": str(error)[:1000]
                if isinstance(error, UsageError)
                else type(error).__name__,
            }
        )
        failures(run_record, str(path), save)
    finally:
        signal.signal(signal.SIGTERM, previous)
        run_record["finished_at"] = now()
        save()
        print(
            f"{run_record['outcome']}; "
            f"failure email {run_record['notification']['status']}. "
            f"Run summary: {path}",
            flush=True,
        )
    return code
