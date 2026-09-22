"""How far the share has drifted from the catalog.

`pending_changes` counts the files whose current location differs from the one the
catalog says they belong in. It uses `compute_placements`, the same function
`reorganize` uses, so a report and the next `reorganize --dry-run` agree.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from .placement import compute_placements


def pending_changes(session: Session) -> dict[str, Any]:
    """`{"total": n, "by_disposition": {"keep": a, "duplicate": b, ...}}`."""
    by_disposition: dict[str, int] = {}
    for placement in compute_placements(session):
        if not placement.settled:
            key = placement.disposition.value
            by_disposition[key] = by_disposition.get(key, 0) + 1
    return {"total": sum(by_disposition.values()), "by_disposition": by_disposition}
