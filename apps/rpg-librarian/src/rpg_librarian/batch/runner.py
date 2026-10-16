"""Run existing commands in isolated stages and always retain a local receipt."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
from contextlib import nullcontext
from pathlib import Path

from ..db import session_scope
from ..errors import UsageError
from ..infrastructure.job_lock import catalog_job_lock
from ..observability import log_call_fields
from ..services.review_backlog import collect
from .inventory import inspect
from .notifications import notify
from .processes import execute
from .records import Run, now, write_json

_STAGES = ("quick-dedupe", "scan", "find-packs", "enrich", "filing", "reorganize")


def stage(run: Run, name: str) -> dict:
    catalog = run.data["catalog"]
    arguments = [name, "--catalog", catalog]
    if name in {"quick-dedupe", "scan", "find-packs"}:
        arguments.extend(["--root", run.data["root"]])
    request = run.directory / f"{name}-request.json"
    write_json(
        request,
        {
            "name": name,
            "catalog": catalog,
            "arguments": arguments,
            "source": run.data.get("source"),
        },
    )
    record = {"name": name, "outcome": "running", "started_at": now()}
    run.data["stages"].append(record)
    run.save()
    env = os.environ.copy()
    env["RPG_LIBRARIAN_BATCH_RUN_ID"] = run.data["run_id"]
    env["PYTHONFAULTHANDLER"] = "1"
    env.pop("RPG_LIBRARIAN_IMPORT_MANIFEST", None)
    print(f"{name}...", flush=True)
    code = execute(
        [sys.executable, "-m", "rpg_librarian.batch.worker", str(request)],
        stdout=run.directory / f"{name}-stdout.log",
        stderr=run.directory / f"{name}-stderr.log",
        env=env,
    )
    record.update(returncode=code, finished_at=now())
    try:
        result = json.loads(
            request.with_name(request.stem + "-result.json").read_text()
        )
        if result["name"] != name or result["outcome"] not in {
            "completed",
            "issues",
            "failed",
        }:
            raise ValueError("Invalid stage result")
        if not isinstance(result["metrics"], dict):
            raise ValueError("Invalid stage metrics")
        record.update(result)
    except (OSError, ValueError, KeyError, TypeError):
        record.update(outcome="failed", error_type="MissingOrInvalidStageResult")
    # A process signal/nonzero code is authoritative even if an earlier result exists.
    record["returncode"] = code
    if code:
        record["outcome"] = "failed"
        if code < 0:
            record["signal"] = -code
    run.save()
    return record


def run_batch(catalog: Path, root: Path) -> int:
    return _run_batch(catalog, root, catalog_job_lock(catalog))


def _run_batch_locked(catalog: Path, root: Path, *, source: str, prepared) -> int:
    """Internal source coordinator entry point; caller holds catalog_job_lock."""
    return _run_batch(
        catalog,
        root,
        nullcontext(),
        source=source,
        notify_failures=False,
        prepared=prepared,
    )


def _run_batch(
    catalog: Path,
    root: Path,
    lock,
    *,
    source: str | None = None,
    notify_failures: bool = True,
    prepared=None,
) -> int:
    run = Run(catalog, root)
    if source is not None:
        run.data["source"] = source
        run.save()
    if prepared is not None:
        prepared(run)
    print(f"Run summary: {run.path}", flush=True)
    previous_handler = signal.getsignal(signal.SIGTERM)
    terminated = False

    def terminate(signum, frame):
        nonlocal terminated
        terminated = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    code = 1
    try:
        # Keep the lock through final reporting; child processes do not reacquire it.
        with lock:
            run.recover_abandoned()
            try:
                run.data["inventory"] = inspect(catalog, root)
                inventory = run.data["inventory"]
                run.data["new_input"] = inventory["new"] + inventory["changed"]
                run.save()
                if not shutil.which("claude"):
                    raise UsageError("Install and sign in to the Claude CLI first.")
                for name in _STAGES:
                    result = stage(run, name)
                    if result["outcome"] == "failed" and name != "quick-dedupe":
                        break
                else:
                    run.data["outcome"] = (
                        "issues"
                        if any(s["outcome"] != "completed" for s in run.data["stages"])
                        else "completed"
                    )
                if run.data["outcome"] == "running":
                    run.data["outcome"] = "failed"
            except KeyboardInterrupt:
                run.data["outcome"] = "interrupted"
                code = 143 if terminated else 130
            except Exception as error:
                run.data.update(outcome="failed", error_type=type(error).__name__)
                # Text may contain paths/evidence; it stays in the private local record.
                run.data["error"] = str(error)[:1000]
            finally:
                for name in _STAGES:
                    if not any(s["name"] == name for s in run.data["stages"]):
                        run.data["stages"].append({"name": name, "outcome": "skipped"})
                for record in run.data["stages"]:
                    if record["outcome"] == "running":
                        record.update(outcome="interrupted", finished_at=now())
                try:
                    with session_scope(catalog, migrate=False) as session:
                        backlog = collect(session)
                    # Full details remain available through MCP.
                    run.data["backlog"] = {k: backlog[k] for k in ("total", "counts")}
                except Exception as error:
                    run.data["backlog_error_type"] = type(error).__name__
                    if run.data["outcome"] == "completed":
                        run.data["outcome"] = "issues"
                run.data["finished_at"] = now()
                run.save()
                if not notify_failures and run.data["outcome"] != "completed":
                    run.data["notification"] = {
                        "status": "skipped",
                        "reason": "sync_failure_summary",
                    }
                    run.save()
                    delivered = True
                else:
                    delivered = notify(run)
                if run.data["outcome"] != "interrupted":
                    code = 0 if run.data["outcome"] == "completed" and delivered else 1
    except UsageError as error:
        run.data.update(
            outcome="failed",
            error_type=type(error).__name__,
            error=str(error),
            finished_at=now(),
            notification={"status": "skipped", "reason": "job_lock_unavailable"},
        )
        run.save()
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
        log_call_fields(
            batch_run_id=run.data["run_id"],
            summary_path=str(run.path),
            batch_outcome=run.data["outcome"],
            notification=run.data["notification"],
        )
        print(
            f"{run.data['outcome']}; email {run.data['notification']['status']}. "
            f"Run summary: {run.path}",
            flush=True,
        )
    return code
