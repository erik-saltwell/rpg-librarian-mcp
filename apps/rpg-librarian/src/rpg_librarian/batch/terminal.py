"""Human-facing batch status; private logs remain the detailed source of evidence."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

LABELS = {
    "quick-dedupe": "Quick dedupe",
    "scan": "Scan",
    "find-packs": "Find packs",
    "enrich": "Enrich",
    "filing": "File products",
    "reorganize": "Reorganize",
}


def clean(value) -> str:
    return "".join(c for c in str(value) if c.isprintable())[:500]


def duration(seconds: float) -> str:
    value = max(0, int(seconds))
    hours, value = divmod(value, 3600)
    minutes, seconds = divmod(value, 60)
    return (
        f"{hours:d}:{minutes:02d}:{seconds:02d}"
        if hours
        else f"{minutes:02d}:{seconds:02d}"
    )


def unit_name(unit: str, count: int) -> str:
    if count != 1:
        return unit
    return {
        "files": "file",
        "entries": "entry",
        "queries": "query",
        "folders": "folder",
        "items": "item",
    }.get(unit, unit)


class StageDisplay:
    def __init__(self, title: str, path: Path | None = None):
        self.console = Console(stderr=True, highlight=False)
        self.title, self.path = title, path
        self.started = time.monotonic()
        self.snapshot: dict = {
            "description": "Preparing",
            "detail": "Starting",
            "updated_at": self.started,
        }
        self.last_signature = None
        self.last_emit = 0.0
        self.last_phase = None
        self.last_errors = 0
        self.notices_shown = 0
        self.more_notices = False
        self.live: Live | None = None

    def __enter__(self):
        if self.console.is_terminal and not self.console.is_dumb_terminal:
            self.live = Live(
                console=self.console,
                get_renderable=self.render,
                refresh_per_second=4,
                transient=True,
            )
            self.live.start()
        else:
            self.console.print(Text(f"{self.title} started"))
        return self

    def __exit__(self, exc_type, exc, tb):
        self.tick()
        if self.live is not None:
            self.live.stop()
        if exc_type is not None:
            self.console.print(
                Text(
                    f"{self.title} interrupted after "
                    f"{duration(time.monotonic() - self.started)}"
                    if issubclass(exc_type, KeyboardInterrupt)
                    else f"{self.title} stopped after "
                    f"{duration(time.monotonic() - self.started)}",
                    style="yellow",
                )
            )
            self.console.print(Text("  " + self.status()))
            if self.snapshot.get("detail"):
                self.console.print(Text("  " + clean(self.snapshot["detail"])))
        return False

    def update(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        self.tick()

    def counts(self) -> str:
        data = self.snapshot
        if data.get("counts"):
            return clean(data["counts"])
        total, done = data.get("total"), data.get("completed", 0)
        unit = clean(data.get("unit", "items"))
        if total is None:
            return f"{done:,} {unit_name(unit, done)}" if done else ""
        if not total:
            return "No work"
        return (
            f"{done:,}/{total:,} {unit_name(unit, total)} "
            f"({min(100, done / total * 100):.0f}%)"
        )

    def status(self) -> str:
        errors = self.snapshot.get("errors", 0)
        parts = [clean(self.snapshot.get("description", "Working")), self.counts()]
        if errors:
            parts.append(f"{errors:,} error" + ("s" if errors != 1 else ""))
        return " · ".join(part for part in parts if part)

    def waiting(self) -> str:
        age = time.monotonic() - self.snapshot.get("updated_at", self.started)
        return (
            f"Waiting for current operation · last progress {duration(age)} ago"
            if age >= 15
            else ""
        )

    def render(self):
        header = Table.grid(expand=True)
        header.add_column(width=2)
        header.add_column(ratio=1)
        header.add_column(justify="right")
        header.add_row(
            Spinner("dots", style="cyan"),
            Text(self.title, style="bold"),
            Text(duration(time.monotonic() - self.started)),
        )
        rows = [header, Text(self.status())]
        total = self.snapshot.get("total")
        if total:
            bar = Table.grid(expand=True)
            bar.add_column(ratio=1)
            bar.add_row(
                ProgressBar(
                    total=total, completed=self.snapshot.get("completed", 0), width=None
                )
            )
            rows.append(bar)
        detail = self.snapshot.get("detail")
        if detail:
            rows.append(
                Text(clean(detail), style="dim", overflow="ellipsis", no_wrap=True)
            )
        if waiting := self.waiting():
            rows.append(Text(waiting, style="yellow"))
        return Group(*rows)

    def tick(self) -> None:
        if self.path is not None:
            try:
                stat = self.path.stat()
                if (
                    stat.st_mtime_ns != self.last_signature
                    and stat.st_size <= 64 * 1024
                ):
                    data = json.loads(self.path.read_text())
                    if data.get("version") == 1 and isinstance(
                        data.get("description"), str
                    ):
                        self.snapshot = data
                        self.last_signature = stat.st_mtime_ns
            except (OSError, ValueError, TypeError):
                pass
        notices = self.snapshot.get("notices", [])
        for notice in notices[self.notices_shown :]:
            self.console.print(Text("  ! " + clean(notice), style="yellow"))
        self.notices_shown = len(notices)
        if self.snapshot.get("notice_count", 0) > 5 and not self.more_notices:
            self.console.print(
                Text("  ! Further issues are recorded in events.log.", style="yellow")
            )
            self.more_notices = True
        if self.live is not None:
            return
        clock = time.monotonic()
        phase = self.snapshot.get("description")
        errors = self.snapshot.get("errors", 0)
        if (
            phase != self.last_phase
            or clock - self.last_emit >= 15
            or (errors != self.last_errors and clock - self.last_emit >= 1)
        ):
            parts = [f"  {self.status()}", f"elapsed {duration(clock - self.started)}"]
            if detail := self.snapshot.get("detail"):
                parts.append(clean(detail))
            if waiting := self.waiting():
                parts.append(waiting)
            self.console.print(Text(" · ".join(parts)), soft_wrap=True)
            self.last_emit, self.last_phase, self.last_errors = clock, phase, errors

    def finish(self, record: dict) -> None:
        outcome = record["outcome"]
        style = (
            "green"
            if outcome == "completed"
            else "red"
            if outcome == "failed"
            else "yellow"
        )
        label = "completed with issues" if outcome == "issues" else outcome
        self.console.print(
            Text(
                f"{self.title} {label} · {duration(time.monotonic() - self.started)}",
                style=style,
            )
        )
        for line in metrics(record):
            self.console.print(Text("  " + line))
        if outcome != "completed" and self.path is not None:
            location = (
                self.path.parent / (record["name"] + "-stderr.log")
                if outcome == "failed"
                else self.path.parents[2] / "events.log"
            )
            self.console.print(Text(f"  Details: {location}", style="dim"))


def metrics(record: dict) -> list[str]:
    data, name = record.get("metrics", {}), record["name"]
    keys = {
        "quick-dedupe": [
            ("seen", "checked"),
            ("hashed", "hashed"),
            ("duplicates", "duplicates"),
            ("trashed", "trashed"),
            ("survivors", "survivors"),
            ("already_cataloged_skipped", "already cataloged"),
            ("errors", "errors"),
            ("move_errors", "move errors"),
        ],
        "scan": [
            ("seen", "seen"),
            ("skipped", "unchanged"),
            ("new", "new"),
            ("changed", "changed"),
            ("retry", "retried"),
            ("errored", "errors"),
        ],
        "find-packs": [
            ("folders_asked", "folders judged"),
            ("calls", "model calls"),
            ("reused", "cached judgments"),
            ("formed", "packs formed"),
            ("mixed", "mixed folders"),
            ("errors", "errors"),
            ("search_errors", "search errors"),
            ("not_asked", "not asked"),
        ],
        "filing": [
            ("eligible_before", "initial unfiled entries"),
            ("remaining", "remaining unfiled"),
        ],
        "reorganize": [
            ("moved", "moved"),
            ("renamed", "renamed"),
            ("copied", "copied"),
            ("trashed", "trashed"),
            ("settled", "already placed"),
            ("blocked", "blocked"),
            ("errors", "errors"),
            ("not_attempted", "not attempted"),
            ("unreachable", "unreachable"),
        ],
    }
    result = []
    if name == "enrich":
        for source, values in data.get("sources", {}).items():
            if values.get("skipped_reason"):
                result.append(f"{source}: skipped ({clean(values['skipped_reason'])})")
                continue
            parts = [
                f"{values.get('attempted', 0):,} entries checked",
                f"{values.get('with_results', 0):,} with results",
                f"{values.get('empty', 0):,} empty",
                f"{values.get('errors', 0):,} errors",
            ]
            result.append(f"{source}: " + " · ".join(parts))
            if values.get("stopped_reason"):
                result.append(f"{source} stopped: {clean(values['stopped_reason'])}")
    else:
        parts = [
            f"{data[key]:,} {label}"
            for key, label in keys.get(name, [])
            if isinstance(data.get(key), int)
        ]
        if parts:
            result.append(" · ".join(parts))
    if record.get("signal"):
        result.append(f"Worker terminated by signal {record['signal']}")
    elif record.get("error_type"):
        result.append(f"Worker error: {clean(record['error_type'])}")
    for key in ("skipped_reason", "stopped", "search_disabled"):
        if data.get(key):
            result.append(
                f"{key.replace('_', ' ')}: {clean(data[key]).replace('_', ' ')}"
            )
    return result


def final_summary(run) -> None:
    console = Console(stderr=True, highlight=False)
    data = run.data
    try:
        elapsed = (
            datetime.fromisoformat(data["finished_at"])
            - datetime.fromisoformat(data["started_at"])
        ).total_seconds()
    except (ValueError, TypeError):
        elapsed = 0
    outcome = (
        "completed with issues" if data["outcome"] == "issues" else data["outcome"]
    )
    console.print(Text(f"Batch {outcome} · total {duration(elapsed)}", style="bold"))
    for stage in data["stages"]:
        console.print(Text(f"  {LABELS[stage['name']]}: {stage['outcome']}"))
    backlog = data.get("backlog")
    console.print(
        Text(
            f"Review backlog: {backlog['total']:,}"
            if backlog
            else "Review backlog: unavailable"
        )
    )
    notification = data["notification"]
    console.print(
        Text(
            f"Email: {notification['status']}"
            + (
                f" ({notification['reason'].replace('_', ' ')})"
                if notification.get("reason")
                else ""
            )
        )
    )
    if data.get("error"):
        console.print(Text(clean(data["error"]), style="red"))
