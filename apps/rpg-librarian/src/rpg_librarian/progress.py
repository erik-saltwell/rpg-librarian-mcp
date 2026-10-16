"""Standalone Rich progress and a private structured channel for batch workers."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Column

ProgressUpdate = Callable[[int, str, int], None]
_path: Path | None = None
_owner: int | None = None
_state: dict = {}
_written = 0.0


def configure(path: Path) -> None:
    """Only the stage worker writes snapshots; forked extraction workers do not."""
    global _path, _owner, _state, _written
    _path, _owner, _state, _written = path, os.getpid(), {}, 0.0
    report("Preparing", detail="Loading stage")


def active() -> bool:
    return _path is not None and _owner == os.getpid()


def _save(*, force: bool = False) -> None:
    global _written
    if not active():
        return
    clock = time.monotonic()
    if not force and clock - _written < 0.5:
        return
    from .batch.records import write_json

    try:
        assert _path is not None
        write_json(_path, {"version": 1, **_state, "updated_at": clock})
        _written = clock
    except OSError:
        # Display failure must never turn successful processing into a failed stage.
        pass


def report(
    description: str,
    *,
    completed: int = 0,
    total: int | None = None,
    unit: str = "items",
    detail: str = "",
    errors: int = 0,
    counts: str = "",
    force: bool = False,
) -> None:
    if not active():
        return
    changed = description != _state.get("description") or errors != _state.get("errors")
    _state.update(
        description=description,
        completed=completed,
        total=total,
        unit=unit,
        detail=detail,
        errors=errors,
        counts=counts,
    )
    _save(force=force or changed)


def activity(detail: str) -> None:
    """Change the operation/file without resetting its enclosing progress counts."""
    if active():
        _state["detail"] = detail
        _save(force=True)


def warning(detail: str) -> None:
    """Keep a few actionable issues visible without dumping document/model text."""
    if active():
        _state["notice_count"] = _state.get("notice_count", 0) + 1
        notices = _state.setdefault("notices", [])
        if len(notices) < 5:
            notices.append(detail[:500])
        _save(force=True)


@contextmanager
def track(
    description: str, total: int, *, unit: str = "files"
) -> Iterator[ProgressUpdate]:
    """Yield update(completed, current filename, errors); never guess completion."""
    if active():
        report(description, total=total, unit=unit, force=True)

        def update(current: int, filename: str, errors: int) -> None:
            report(
                description,
                completed=current,
                total=total,
                unit=unit,
                detail=filename,
                errors=errors,
            )

        try:
            yield update
        finally:
            _save(force=True)
        return
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        TextColumn("- {task.completed}/{task.total}"),
        TextColumn("- {task.fields[errors]} errors"),
        BarColumn(),
        TimeElapsedColumn(),
        TextColumn(
            "{task.fields[filename]}",
            markup=False,
            table_column=Column(no_wrap=True, overflow="ellipsis", ratio=1),
        ),
        console=Console(stderr=True),
        expand=True,
    )

    def update(current: int, filename: str, errors: int) -> None:
        progress.update(task_id, completed=current, filename=filename, errors=errors)

    with progress:
        task_id = progress.add_task(description, total=total, filename="", errors=0)
        yield update


def tool_activity(name: str, status: str) -> None:
    """Optional filing-only MCP signal; never includes arguments or model content."""
    destination = os.environ.get("RPG_LIBRARIAN_TOOL_ACTIVITY_PATH")
    if destination:
        from .batch.records import write_json

        with suppress(OSError):
            write_json(
                Path(destination),
                {"tool": name, "status": status, "updated_at": time.monotonic()},
            )
