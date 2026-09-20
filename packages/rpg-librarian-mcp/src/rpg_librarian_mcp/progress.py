"""Progress reporting for `UpdateBaseCommand`/`UpdateCatalogCommand` runs.

Each command's per-entry loop reports progress the same way regardless of
caller -- via a `ProgressReporter`, which owns *how* (and whether) each
update is actually surfaced. MCP mode throttles to integer-percent changes
and forwards to `Context.report_progress`; CLI mode renders every update as
a live, in-place `rich` progress bar. The loop itself just calls `update()`
unconditionally for every entry, skipped or processed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from fastmcp import Context
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Column

ProgressUpdate = Callable[[int, str, int], Awaitable[None]]


class ProgressReporter(Protocol):
    def track(self, total: int) -> AbstractAsyncContextManager[ProgressUpdate]:
        """An async context manager yielding an `update(current, filename,
        errors)` callable, valid only for the duration of the `with` block."""
        ...


class McpProgressReporter:
    """Reports progress to an MCP client, throttled to integer-percent
    changes -- MCP clients render their own progress UI from the numeric
    `progress`/`total` args, so a message on every entry would be redundant
    over the wire."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    @asynccontextmanager
    async def track(self, total: int) -> AsyncIterator[ProgressUpdate]:
        last_percent = -1

        async def update(current: int, filename: str, errors: int) -> None:
            nonlocal last_percent
            percent = current * 100 // total if total else 100
            if percent == last_percent:
                return
            last_percent = percent
            await self._ctx.report_progress(
                current,
                total,
                f"Processing: {filename} - {errors} errors - {current}/{total}",
            )

        yield update


class CliProgressReporter:
    """Renders an in-place `rich` progress bar to stderr, updated on every
    entry (skipped or processed) -- stdout stays clean for the command's
    JSON result."""

    @asynccontextmanager
    async def track(self, total: int) -> AsyncIterator[ProgressUpdate]:
        # The filename column is last (after the bar) and no_wrap/ellipsis so
        # that its arbitrary length can't shift the fixed-width columns --
        # count, error total, bar -- that come before it.
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            TextColumn("- {task.completed}/{task.total}"),
            TextColumn("- {task.fields[errors]} errors"),
            BarColumn(),
            TextColumn(
                "{task.fields[filename]}",
                table_column=Column(no_wrap=True, overflow="ellipsis"),
            ),
            console=Console(stderr=True),
        )

        async def update(current: int, filename: str, errors: int) -> None:
            progress.update(
                task_id,
                completed=current,
                filename=filename,
                errors=errors,
            )

        with progress:
            task_id = progress.add_task(
                "Processing", total=total, filename="", errors=0
            )
            yield update
