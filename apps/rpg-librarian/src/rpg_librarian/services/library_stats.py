"""Write a markdown stats report beside the catalog after each nightly sync."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..db import readonly_connection
from ..paths import TRASH_DIRNAME

REPORT_NAME = "library-stats.md"
WINDOW_DAYS = 28


def write_report(catalog: Path, *, now: datetime | None = None) -> Path:
    now = now or datetime.now(UTC)
    path = catalog.parent / REPORT_NAME
    text = render(catalog, now)
    partial = path.with_suffix(".md.part")
    partial.write_text(text)
    partial.replace(path)
    return path


def render(catalog: Path, now: datetime) -> str:
    totals, by_type, by_month, first_seen = library_counts(catalog)
    local_now = now.astimezone()
    lines = [
        "# Library stats",
        "",
        f"Generated {local_now:%Y-%m-%d %H:%M %Z} from `{catalog}`.",
        "",
        "## Library now",
        "",
        f"**{totals:,} files** across **{len(by_type)} product types**.",
        "",
        "| Product type | Files |",
        "|---|---:|",
    ]
    lines += [f"| {name} | {count:,} |" for name, count in by_type]
    lines += [
        "",
        "## Files landed by month",
        "",
        "Files now in the library, by the month the catalog first recorded them. "
        f"History starts when the catalog was built ({first_seen}), so the first "
        "months include that initial build rather than real arrivals.",
        "",
        "| Month | Files landed |",
        "|---|---:|",
    ]
    lines += [f"| {month} | {count:,} |" for month, count in by_month]
    lines += ["", f"## Sync runs, past {WINDOW_DAYS} days", ""]
    lines += sync_tables(catalog.parent / "logs" / "sync-sources", now)
    return "\n".join(lines) + "\n"


def library_counts(catalog: Path):
    top = (
        "CASE WHEN instr(f.relative_path,'/')=0 THEN '' "
        "ELSE substr(f.relative_path,1,instr(f.relative_path,'/')-1) END"
    )
    live = (
        "FROM file f JOIN root r ON r.id=f.root_id "
        "WHERE r.kind='library' AND f.missing_since IS NULL "
        f"AND {top} != '{TRASH_DIRNAME}'"
    )
    with readonly_connection(catalog) as db:
        by_type = db.execute(
            f"SELECT {top} t, count(*) {live} GROUP BY t ORDER BY 2 DESC, 1"
        ).fetchall()
        by_month = db.execute(
            f"SELECT substr(f.created_at,1,7) m, count(*) {live} GROUP BY m ORDER BY m"
        ).fetchall()
        first_seen = db.execute(
            f"SELECT substr(min(f.created_at),1,10) {live}"
        ).fetchone()[0]
    by_type = [(name or "(library root)", count) for name, count in by_type]
    return sum(c for _, c in by_type), by_type, by_month, first_seen or "n/a"


COLUMNS = [
    ("Started", lambda s: _local(s.get("started_at"))),
    ("Outcome", lambda s: s.get("outcome", "—")),
    ("Duration", lambda s: _duration(s.get("started_at"), s.get("finished_at"))),
    ("Remote files", lambda s: _n(s.get("observed"))),
    ("Ownership reused", lambda s: _n(s.get("ownership_reused"))),
    ("Ownership re-checked", lambda s: _n(s.get("ownership_reclassified"))),
    ("Downloaded files", lambda s: _n(s.get("downloaded_files"))),
    ("Downloaded GB", lambda s: _gb(s.get("downloaded_bytes"))),
    ("Local files hashed", lambda s: _n(s.get("local_hashed_files"))),
    ("Local GB hashed", lambda s: _gb(s.get("local_hashed_bytes"))),
    ("New files found", lambda s: _n(s.get("pending"))),
    ("Published to inbox", lambda s: _n(s.get("published"))),
    ("Requests", lambda s: _n(s.get("request_attempts"))),
    ("Retries", lambda s: _n(s.get("retry_events"))),
]


def sync_tables(logs: Path, now: datetime) -> list[str]:
    since = now - timedelta(days=WINDOW_DAYS)
    runs: dict[str, list[dict]] = defaultdict(list)
    for summary in sorted(logs.glob("*/summary.json")):
        try:
            record = json.loads(summary.read_text())
        except (OSError, ValueError):
            continue
        for source in record.get("sources", []):
            started = _parse(source.get("started_at") or record.get("started_at"))
            if started is None or started < since:
                continue
            # A setup failure has no source of its own; keep it out of the tables.
            if source.get("name") == "sync setup":
                continue
            runs[source["name"]].append(source)
    if not runs:
        return ["No sync runs in this period."]
    lines = []
    for name in sorted(runs):
        rows = sorted(runs[name], key=lambda s: s.get("started_at") or "", reverse=True)
        lines += [
            f"### {name}",
            "",
            "| " + " | ".join(c for c, _ in COLUMNS) + " |",
            "|"
            + "|".join("---" if i < 2 else "---:" for i in range(len(COLUMNS)))
            + "|",
        ]
        lines += ["| " + " | ".join(f(s) for _, f in COLUMNS) + " |" for s in rows]
        lines.append("")
    lines += [
        "Remote files are everything the source lists. Ownership reused files were "
        "matched from saved proofs; re-checked files needed a fresh comparison, and "
        "some of those had to be downloaded just to hash them. New files found is "
        "what remained after matching; above the threshold, a run stops for manual "
        "approval and publishes nothing. Many downloads with nothing published "
        "means the run is spending bandwidth on checking, not on new content.",
    ]
    return lines


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _local(value: str | None) -> str:
    parsed = _parse(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M") if parsed else "—"


def _duration(start: str | None, end: str | None) -> str:
    begun, ended = _parse(start), _parse(end)
    if not (begun and ended):
        return "—"
    minutes = round((ended - begun).total_seconds() / 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _n(value) -> str:
    return f"{value:,}" if isinstance(value, int) else "—"


def _gb(value) -> str:
    return f"{value / 1e9:,.1f}" if isinstance(value, int) else "—"
