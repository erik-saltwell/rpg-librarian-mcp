"""One definition of the review burden for batch email and interactive agents."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session

from ..errors import UsageError

_QUEUES = ("review_flags", "blocked_moves", "folder_judgments", "organization_findings")
_BLOCK = re.compile(
    r"\[organization finding #(\d+)\].*?\[/organization finding #\1\]", re.DOTALL
)


def collect(session: Session) -> dict[str, Any]:
    # Explicit BEGIN supplies one SQLite read snapshot even with the driver's legacy
    # transaction mode (SELECT alone does not start a database transaction).
    connection = session.connection()
    raw = connection.connection.dbapi_connection
    assert raw is not None
    if not raw.in_transaction:
        connection.exec_driver_sql("BEGIN")

    def rows(sql: str, parameters: tuple = ()) -> list[dict]:
        return [
            dict(row) for row in connection.exec_driver_sql(sql, parameters).mappings()
        ]

    findings = rows("SELECT * FROM organization_finding WHERE status='deferred'")
    deferred = {r["id"] for r in findings}
    entries = {
        r["entry_id"]: r
        for r in rows("""SELECT en.id entry_id, en.type,
            COALESCE(f.root_id,p.root_id) root_id,
            COALESCE(f.relative_path,p.original_root_path) relative_path
            FROM entry en LEFT JOIN file f ON f.id=en.file_id
            LEFT JOIN pack p ON p.id=en.pack_id
            WHERE (f.id IS NULL OR f.missing_since IS NULL)
            AND (en.id IN (SELECT entry_id FROM review_flag WHERE resolved_at IS NULL)
                 OR en.id IN (SELECT entry_id FROM error WHERE stage='reorganize'))""")
    }
    items: dict[str, dict] = {}
    for flag in rows("SELECT * FROM review_flag WHERE resolved_at IS NULL"):
        identity = flag["entry_id"]
        if identity not in entries:
            continue
        reason = _BLOCK.sub(
            lambda m: "" if int(m[1]) in deferred else m[0], flag["reason"]
        ).strip()
        if not reason:
            continue
        key = f"entry:{identity}"
        items[key] = dict(
            entries[identity], key=key, queues=["review_flags"], reason=reason
        )
    for error in rows("SELECT * FROM error WHERE stage='reorganize'"):
        identity = error["entry_id"]
        if identity not in entries:
            continue
        key = f"entry:{identity}"
        item = items.setdefault(key, dict(entries[identity], key=key, queues=[]))
        item["queues"].append("blocked_moves")
        item["blocked_reason"] = error["error_text"]
    folders = rows("""SELECT j.root_id,j.folder,j.outcome,j.reason
        FROM folder_judgment j
        JOIN root r ON r.id=j.root_id WHERE j.outcome IN ('mixed','invalid','error')""")
    for folder in folders:
        key = f"folder:{folder['root_id']}:{folder['folder']}"
        items[key] = dict(folder, key=key, queues=["folder_judgments"])
    finding_files = sorted({i for f in findings for i in json.loads(f["file_ids"])})
    current_entries: dict[int, int | None] = {}
    for start in range(0, len(finding_files), 400):
        subset = finding_files[start : start + 400]
        marks = ",".join("?" for _ in subset)
        current_entries.update(
            {
                r["file_id"]: r["entry_id"]
                for r in rows(
                    f"""SELECT f.id file_id, COALESCE(en.id,pe.id) entry_id
                FROM file f LEFT JOIN entry en ON en.file_id=f.id
                LEFT JOIN entry pe ON pe.pack_id=f.pack_id
                WHERE f.missing_since IS NULL AND f.id IN ({marks})""",
                    tuple(subset),
                )
            }
        )
    for finding in findings:
        file_ids = json.loads(finding["file_ids"])
        key = f"finding:{finding['id']}"
        items[key] = {
            "key": key,
            "queues": ["organization_findings"],
            "finding_id": finding["id"],
            "current_entry_ids": sorted(
                {
                    current_entries[i]
                    for i in file_ids
                    if current_entries.get(i) is not None
                }
            ),
            "record": json.loads(finding["record"]),
        }
    ordered = sorted(items.values(), key=lambda r: r["key"])
    return {
        "total": len(ordered),
        "counts": {q: sum(q in item["queues"] for item in ordered) for q in _QUEUES},
        "items": ordered,
    }


def review_backlog(
    session: Session, *, after_key: str = "", limit: int = 100
) -> dict[str, Any]:
    if not 1 <= limit <= 500:
        raise UsageError("limit must be between 1 and 500.")
    result = collect(session)
    remaining = [item for item in result["items"] if item["key"] > after_key]
    selected = remaining[:limit]
    truncated = len(remaining) > limit
    return {
        **result,
        "items": selected,
        "truncated": truncated,
        "next_after_key": selected[-1]["key"] if truncated else None,
    }
