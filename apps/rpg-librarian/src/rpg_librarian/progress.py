"""An in-place `rich` progress bar on stderr, so stdout stays clean for results."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Column

ProgressUpdate = Callable[[int, str, int], None]


@contextmanager
def track(description: str, total: int) -> Iterator[ProgressUpdate]:
    """Yield an `update(current, filename, errors)` callable for the block."""
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        TextColumn("- {task.completed}/{task.total}"),
        TextColumn("- {task.fields[errors]} errors"),
        BarColumn(),
        TextColumn(
            "{task.fields[filename]}",
            # A ratio column in an expanded table gets only the width left over
            # by the fixed columns, so just the filename is truncated (at its end).
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
