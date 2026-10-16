"""Resumable catalog reviews and atomic, optimistic group corrections.

No filesystem writes or LLM calls live here. The invoking agent supplies judgment;
these services retain its evidence, enforce scope, and make decisions durable.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from ..errors import UsageError
from ..model import (
    Disposition,
    Entry,
    File,
    OrganizationCoverage,
    OrganizationFinding,
    OrganizationRun,
    Pack,
    Product,
    ProductLine,
    ProductLineAlias,
    ProductType,
    ReviewFlag,
)
from ..model.core import utc_now
from . import packs
from .update_product import UpdateProductRequest, update_product


class ProtectedDecision(UsageError):
    """An unchanged owner decision must not become another review question."""


class Operation(BaseModel):
    """An ordered correction; a key can name generated entries in later operations."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["assign_product", "create_pack", "add_to_pack", "remove_from_pack"]
    key: str | None = None
    entry_ids: list[int | str] = PydanticField(default_factory=list)
    file_ids: list[int] = PydanticField(default_factory=list)
    folder: str | None = None
    root_id: int | None = None
    product_type: str | None = None
    product_line: str | None = None
    product: str | None = None
    create_line: bool = False


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_ids: list[int]
    current: str
    proposed: str
    evidence: str
    operations: list[Operation] = PydanticField(default_factory=list)


# Do not select sampled document text, mtime, or extraction timestamps. Identical
# refreshes do not invalidate coverage. Membership and product coordinates do.
_ROWS = """
SELECT f.id AS file_id, e.id AS entry_id, e.type AS entry_type,
 f.root_id, f.relative_path, f.size_bytes, f.sha256, f.media_type, f.pack_id,
 COALESCE(p.disposition, f.disposition) AS disposition,
 e.product_id, pr.name AS product, pr.publisher, pr.year, pr.description,
 l.id AS line_id, l.name AS product_line, pt.name AS product_type,
 p.root_id AS pack_root_id, p.original_root_path AS pack_folder,
 m.title, m.artist, m.publisher AS embedded_publisher,
 t.isbn, t.issn, a.description AS hint, a.possible_system,
 g.results AS google, d.results AS dtrpg, rg.results AS rpggeek,
 ir.results AS isbn_evidence
FROM file f
LEFT JOIN pack p ON p.id=f.pack_id
JOIN entry e ON e.file_id=f.id OR e.pack_id=f.pack_id
LEFT JOIN product pr ON pr.id=e.product_id
LEFT JOIN product_line l ON l.id=pr.product_line_id
LEFT JOIN product_type pt ON pt.id=l.product_type_id
LEFT JOIN file_metadata m ON m.file_id=f.id
LEFT JOIN file_text t ON t.file_id=f.id
LEFT JOIN file_text_analysis a ON a.entry_id=e.id
LEFT JOIN google_search_result g ON g.entry_id=e.id
LEFT JOIN dtrpg_result d ON d.entry_id=e.id
LEFT JOIN rpggeek_result rg ON rg.entry_id=e.id
LEFT JOIN isbn_result ir ON ir.file_id=f.id
WHERE f.missing_since IS NULL
AND COALESCE(p.disposition,f.disposition) IN ('keep','superseded','unfiled')
ORDER BY f.id
"""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


_EXTERNAL = {"google", "dtrpg", "rpggeek", "isbn_evidence", "pack_evidence"}


def _compact(row: dict) -> dict:
    """Avoid repeating a large pack's external evidence once per member."""
    return {k: v for k, v in row.items() if k not in _EXTERNAL}


def _group(row: dict) -> str:
    if row["product_id"] is not None:
        return f"product:{row['product_id']}"
    root = row["pack_root_id"] if row["pack_id"] else row["root_id"]
    folder = (
        row["pack_folder"]
        if row["pack_id"]
        else str(PurePosixPath(row["relative_path"]).parent)
    )
    return f"folder:{root}:{folder}"


def _facts(row: dict) -> dict:
    # Owner decisions are protected until content/evidence changes, not merely
    # because a different assignment or a physical move changed the group.
    return {
        "filename": PurePosixPath(row["relative_path"]).name,
        **{
            k: row[k]
            for k in (
                "file_id",
                "size_bytes",
                "sha256",
                "media_type",
                "title",
                "artist",
                "embedded_publisher",
                "isbn",
                "issn",
                "hint",
                "possible_system",
                "evidence_hash",
            )
        },
    }


def _rows(
    session: Session, keys: list[str] | None = None, file_ids: list[int] | None = None
):
    conditions = []
    parameters = {}
    for index, key in enumerate(keys or []):
        try:
            kind, identity, *rest = key.split(":", 2)
            parameters[f"id{index}"] = int(identity)
        except (ValueError, TypeError) as error:
            raise UsageError("Invalid organization group key.") from error
        if kind in ("product", "line"):
            column = "e.product_id" if kind == "product" else "l.id"
            conditions.append(f"{column}=:id{index}")
        elif kind == "folder" and rest:
            folder = rest[0]
            parameters[f"folder{index}"] = folder
            if folder == ".":
                loose = "instr(f.relative_path,'/')=0"
            else:
                prefix = (
                    folder.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
                    + "/"
                )
                parameters[f"prefix{index}"] = prefix + "%"
                parameters[f"length{index}"] = len(folder) + 2
                loose = (
                    f"f.relative_path LIKE :prefix{index} ESCAPE '\\' "
                    f"AND instr(substr(f.relative_path,:length{index}),'/')=0"
                )
            conditions.append(
                f"(e.product_id IS NULL AND ((f.pack_id IS NOT NULL "
                f"AND p.root_id=:id{index} AND p.original_root_path=:folder{index}) "
                f"OR (f.pack_id IS NULL AND f.root_id=:id{index} AND {loose})))"
            )
        else:
            raise UsageError("Group key must identify a product, line, or folder.")
    if file_ids:
        # Integer IDs come from validated arguments, never SQL fragments.
        conditions.append("f.id IN (" + ",".join(str(int(i)) for i in file_ids) + ")")
    sql = _ROWS
    if keys is not None or file_ids is not None:
        sql = sql.replace(
            "ORDER BY f.id",
            "AND (" + (" OR ".join(conditions) or "0") + ") ORDER BY f.id",
        )
    contexts = {}
    for raw in session.connection().execute(text(sql), parameters).mappings():
        row = dict(raw)
        context = contexts.get(row["entry_id"])
        if context is None:
            row["pack_evidence"] = (
                session.connection()
                .execute(
                    text("SELECT evidence FROM pack WHERE id=:identity"),
                    {"identity": row["pack_id"]},
                )
                .scalar_one()
                if row["pack_id"] is not None
                else None
            )
            for key in _EXTERNAL:
                if isinstance(row[key], str):
                    row[key] = json.loads(row[key])
            context = {k: row[k] for k in (*_EXTERNAL, "hint", "possible_system")}
            context["evidence_hash"] = _digest({k: row[k] for k in _EXTERNAL})
            contexts[row["entry_id"]] = context
        row.update(context)
        yield row


def _fingerprint(file_hashes: list[str], coordinates: list[dict]) -> str:
    return _digest({"files": file_hashes, "lines": coordinates})


@dataclass
class View:
    rows: dict[int, dict] = field(default_factory=dict)
    groups: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    lines: dict[int, dict] = field(default_factory=dict)
    products: dict[int, dict] = field(default_factory=dict)
    aliases: dict[int, list[str]] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def load(
        cls,
        session: Session,
        keys: list[str] | None = None,
        file_ids: list[int] | None = None,
    ) -> View:
        view = cls()
        for row in _rows(session, keys, file_ids):
            view.rows[row["file_id"]] = row
            view.groups[_group(row)].append(row["file_id"])
        types = {kind.id: kind for kind in session.exec(select(ProductType)).all()}
        for line in session.exec(select(ProductLine)).all():
            assert line.id is not None
            kind = types.get(line.product_type_id)
            view.lines[line.id] = {
                "id": line.id,
                "name": line.name,
                "product_type": kind.name if kind else None,
            }
        for product in session.exec(select(Product)).all():
            assert product.id is not None
            view.products[product.id] = {
                "id": product.id,
                "name": product.name,
                "line_id": product.product_line_id,
            }
        for raw in session.connection().execute(
            text("SELECT product_line_id,alias FROM product_line_alias ORDER BY alias")
        ):
            view.aliases[raw[0]].append(raw[1])
        return view

    def files(self, key: str) -> list[int]:
        if key.startswith("line:"):
            try:
                identity = int(key.split(":", 1)[1])
            except ValueError as error:
                raise UsageError("Invalid line group key.") from error
            if identity not in self.lines:
                raise UsageError(f"No product line for {key}.")
            return [i for i, r in self.rows.items() if r["line_id"] == identity]
        if key.startswith("product:"):
            try:
                identity = int(key.split(":", 1)[1])
            except ValueError as error:
                raise UsageError("Invalid product group key.") from error
            if identity not in self.products:
                raise UsageError(f"No product for {key}.")
        elif not key.startswith("folder:"):
            raise UsageError(
                "Group key must be product:<id>, line:<id>, or folder:<root>:<path>."
            )
        return self.groups.get(key, [])

    def snapshot(self, key: str) -> dict:
        identities = self.files(key)
        lines = sorted(
            {
                self.rows[i]["line_id"]
                for i in identities
                if self.rows[i]["line_id"] is not None
            }
        )
        if key.startswith("line:"):
            lines = [int(key.split(":", 1)[1])]
        coordinates = [dict(self.lines[i], aliases=self.aliases[i]) for i in lines]
        contents = [_compact(self.rows[i]) for i in identities]
        fingerprint = _fingerprint([_digest(row) for row in contents], coordinates)
        return {
            "group_key": key,
            "fingerprint": fingerprint,
            "file_count": len(identities),
            "entry_count": len({r["entry_id"] for r in contents}),
            "lines": coordinates,
        }

    def evidence(self, identities: list[int]) -> str:
        return _digest(
            [_facts(self.rows[i]) for i in sorted(set(identities)) if i in self.rows]
        )


def _decision_context(view: View, identities: set[int]) -> dict[str, str]:
    groups = {_group(view.rows[i]) for i in identities if i in view.rows}
    fingerprints = {key: view.evidence(view.files(key)) for key in groups}
    return {
        str(i): fingerprints[_group(view.rows[i])] for i in identities if i in view.rows
    }


def _lock(session: Session) -> None:
    # Acquire the SQLite writer reservation before checking optimistic snapshots.
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _run(session: Session, identity: int) -> OrganizationRun:
    run = session.get(OrganizationRun, identity)
    if run is None:
        raise UsageError(f"No organization run {identity}.")
    return run


def _history(session: Session, identities: set[int]) -> list[dict]:
    findings = session.exec(
        select(OrganizationFinding).order_by(col(OrganizationFinding.id))
    ).all()
    return [
        {
            "finding_id": f.id,
            "status": f.status,
            "file_ids": f.file_ids,
            "current": f.record.get("current"),
            "proposed": f.record.get("proposed"),
            "evidence": f.record.get("evidence"),
            "resolution_note": f.resolution_note,
            "resolved_at": f.resolved_at,
        }
        for f in findings
        if identities.intersection(f.file_ids)
    ]


def start(session: Session, *, line_id: int | None = None, max_groups: int = 3) -> dict:
    if not 1 <= max_groups <= 20:
        raise UsageError("max_groups must be between 1 and 20.")
    _lock(session)
    scope = f"line:{line_id}" if line_id is not None else "all"
    active = session.exec(
        select(OrganizationRun)
        .where(
            col(OrganizationRun.scope) == scope, col(OrganizationRun.status) == "active"
        )
        .order_by(col(OrganizationRun.id))
    ).first()
    if active is not None:
        assert active.id is not None
        return receipt(session, run_id=active.id)
    view = View.load(session, keys=[])
    if line_id is not None and line_id not in view.lines:
        raise UsageError(f"No product line {line_id}.")
    hashes: dict[str, list[str]] = defaultdict(list)
    line_by_group = {}
    for row in _rows(session, [f"line:{line_id}"] if line_id is not None else None):
        key = _group(row)
        hashes[key].append(_digest(_compact(row)))
        line_by_group[key] = row["line_id"]
    coverage = {
        c.group_key: c for c in session.exec(select(OrganizationCoverage)).all()
    }
    pending = []
    for key in sorted(hashes):
        identity = line_by_group[key]
        coordinates = (
            [dict(view.lines[identity], aliases=view.aliases[identity])]
            if identity is not None
            else []
        )
        fingerprint = _fingerprint(hashes[key], coordinates)
        previous = coverage.get(key)
        if previous is None or previous.fingerprint != fingerprint:
            pending.append((previous is not None, key))
    pending.sort()
    run = OrganizationRun(
        scope=scope, group_keys=[key for _, key in pending[:max_groups]]
    )
    if not run.group_keys:
        run.status = "complete"
    session.add(run)
    session.flush()
    assert run.id is not None
    result = receipt(session, run_id=run.id)
    result["pending_groups_at_start"] = len(pending)
    return result


def inspect(
    session: Session, *, group_key: str, offset: int = 0, limit: int = 100
) -> dict:
    if offset < 0 or not 1 <= limit <= 500:
        raise UsageError("offset must be nonnegative and limit between 1 and 500.")
    view = View.load(session, keys=[group_key])
    identities = view.files(group_key)
    page = identities[offset : offset + limit]
    result = view.snapshot(group_key)
    # Full external evidence remains available through report_entry; keeping the
    # member listing short makes even very large packs inspectable by pagination.
    result["files"] = [_compact(view.rows[i]) for i in page]
    result["offset"] = offset
    result["next_offset"] = (
        offset + len(page) if offset + len(page) < len(identities) else None
    )
    result["history"] = _history(session, set(page))
    entry_ids = {view.rows[i]["entry_id"] for i in page}
    result["entry_review_history"] = [
        {
            "entry_id": flag.entry_id,
            "reason": flag.reason,
            "resolved_at": flag.resolved_at,
            "resolution_note": flag.resolution_note,
        }
        for flag in session.exec(
            select(ReviewFlag).where(col(ReviewFlag.entry_id).in_(entry_ids))
        ).all()
    ]
    previous = session.get(OrganizationCoverage, group_key)
    result["last_review"] = (
        {"summary": previous.summary, "reviewed_at": previous.reviewed_at}
        if previous
        else None
    )
    return result


def receipt(session: Session, *, run_id: int) -> dict:
    run = _run(session, run_id)
    done = {r["group_key"] for r in run.results}
    pending = [key for key in run.group_keys if key not in done]
    return {
        "run_id": run.id,
        "status": run.status,
        "scope": run.scope,
        "examined": run.results,
        "remaining_groups": pending,
        "resume_at": pending[0] if pending else None,
        "next_call": "organization_review_start"
        if not pending
        else "organization_review_group",
        "physical_moves": "Catalog only; use reorganize separately.",
    }


def _expected(view: View, expected: dict[str, str], primary: str) -> set[int]:
    if primary not in expected:
        raise UsageError("Include the primary group's fingerprint in expected.")
    allowed: set[int] = set()
    for key, fingerprint in expected.items():
        if view.snapshot(key)["fingerprint"] != fingerprint:
            raise UsageError(
                f"{key} changed since inspection. Refresh its group report; "
                "nothing was changed."
            )
        allowed.update(view.files(key))
    return allowed


def _entry_files(session: Session, identity: int) -> set[int]:
    entry = session.get(Entry, identity)
    if entry is None:
        raise UsageError(f"Entry {identity} no longer exists.")
    return (
        {entry.file_id}
        if entry.file_id is not None
        else set(
            session.exec(
                select(File.id).where(col(File.pack_id) == entry.pack_id)
            ).all()
        )
    )


def _resolve(
    identities: list[int | str], references: dict[str, list[int]]
) -> list[int]:
    result = []
    for identity in identities:
        if isinstance(identity, int):
            result.append(identity)
        elif identity in references:
            result.extend(references[identity])
        else:
            raise UsageError(f"Unknown operation reference {identity!r}.")
    return list(dict.fromkeys(result))


def _coordinates(
    session: Session, operation: Operation, expected: dict[str, str]
) -> None:
    if not all((operation.product_type, operation.product_line, operation.product)):
        raise UsageError(
            "Product assignment needs product_type, product_line, and product."
        )
    kind = session.exec(
        select(ProductType).where(col(ProductType.name) == operation.product_type)
    ).first()
    if kind is None:
        raise UsageError(
            "Organization review cannot create product types; use an existing type."
        )
    assert operation.product_line is not None
    from .names import normalize_name

    aliases = session.exec(select(ProductLineAlias)).all()
    line = next(
        (
            candidate
            for candidate in session.exec(select(ProductLine)).all()
            if candidate.product_type_id == kind.id
            and normalize_name(operation.product_line)
            in {
                normalize_name(candidate.name),
                *(
                    normalize_name(a.alias)
                    for a in aliases
                    if a.product_line_id == candidate.id
                ),
            }
        ),
        None,
    )
    if line is not None and f"line:{line.id}" not in expected:
        target = session.exec(
            select(Product).where(
                col(Product.product_line_id) == line.id,
                col(Product.name) == operation.product,
            )
        ).first()
        if target is None or f"product:{target.id}" not in expected:
            raise UsageError(
                f"Inspect destination line:{line.id} or its existing product group "
                "and include its fingerprint."
            )


def _operations(
    session: Session,
    operations: list[Operation],
    allowed: set[int],
    expected: dict[str, str],
) -> tuple[list[dict], set[int]]:
    references: dict[str, list[int]] = {}
    results = []
    touched: set[int] = set()
    for operation in operations:
        if operation.action in ("add_to_pack", "remove_from_pack") and any(
            (
                operation.folder,
                operation.root_id,
                operation.product_type,
                operation.product_line,
                operation.product,
                operation.create_line,
            )
        ):
            raise UsageError(
                "Pack membership operations take only entry_ids, file_ids, and key; "
                "assign products in a following assign_product operation."
            )
        if operation.action == "assign_product" and any(
            (operation.folder, operation.root_id)
        ):
            raise UsageError("assign_product does not take folder or root_id.")
        entry_ids = _resolve(operation.entry_ids, references)
        selected = set(operation.file_ids)
        for identity in entry_ids:
            selected.update(_entry_files(session, identity))
        if operation.action == "create_pack":
            if operation.folder is None or operation.root_id is None:
                raise UsageError("create_pack needs folder and root_id.")
            selection = packs._select(session, operation.folder, operation.root_id)
            selected.update(f.id for f in selection.files if f.id is not None)
        if not selected or not selected <= allowed:
            raise UsageError(
                "Correction touches files outside inspected groups, "
                "or selects no files."
            )
        touched.update(selected)
        if operation.action == "assign_product":
            if not entry_ids or operation.file_ids:
                raise UsageError("assign_product takes entry_ids, not file_ids.")
            _coordinates(session, operation, expected)
            outcome = []
            for identity in entry_ids:
                entry = session.get(Entry, identity)
                assert entry is not None
                holder = (
                    session.get(File, entry.file_id)
                    if entry.file_id is not None
                    else session.get(Pack, entry.pack_id)
                )
                assert holder is not None
                # Organization correction preserves keep/superseded. Newly identified
                # unfiled content becomes kept; discard is outside this workflow.
                disposition = (
                    holder.disposition
                    if holder.disposition is not Disposition.unfiled
                    else Disposition.keep
                )
                outcome.append(
                    update_product(
                        session,
                        UpdateProductRequest(
                            entry_ids=[identity],
                            disposition=disposition,
                            product_type=operation.product_type,
                            product_line=operation.product_line,
                            product=operation.product,
                            create_line=operation.create_line,
                        ),
                    )
                )
            generated = entry_ids
        elif operation.action == "create_pack":
            if entry_ids or operation.file_ids:
                raise UsageError(
                    "create_pack selects its whole folder; "
                    "do not pass entry_ids or file_ids."
                )
            if any((operation.product_type, operation.product_line, operation.product)):
                _coordinates(session, operation, expected)
            assert operation.folder is not None
            outcome = packs.create_pack(
                session,
                folder=operation.folder,
                root_id=operation.root_id,
                disposition=Disposition.keep if operation.product else None,
                product_type=operation.product_type,
                product_line=operation.product_line,
                product=operation.product,
                create_line=operation.create_line,
                reason="review-organization atomic correction",
            )
            generated = [outcome["pack"]["entry"]["id"]]
        else:
            if len(entry_ids) != 1 or not operation.file_ids:
                raise UsageError(
                    "Pack membership correction needs one pack entry "
                    "and explicit file_ids."
                )
            outcome = []
            generated = []
            for identity in operation.file_ids:
                file = session.get(File, identity)
                if file is None:
                    raise UsageError(f"File {identity} no longer exists.")
                if operation.action == "add_to_pack":
                    result = packs.add_to_pack(
                        session,
                        entry_id=entry_ids[0],
                        path=file.relative_path,
                        root_id=file.root_id,
                    )
                    generated = entry_ids
                else:
                    result = packs.remove_from_pack(
                        session,
                        entry_id=entry_ids[0],
                        path=file.relative_path,
                        root_id=file.root_id,
                    )
                    generated.extend(r["entry_id"] for r in result["removed"])
                outcome.append(result)
        if operation.key:
            if operation.key in references:
                raise UsageError("Operation keys must be unique.")
            references[operation.key] = generated
        results.append(
            {"action": operation.action, "key": operation.key, "result": outcome}
        )
    return results, touched


def _protect(
    session: Session, view: View, identities: set[int], *, new_evidence: str | None
) -> None:
    for finding in session.exec(
        select(OrganizationFinding).where(
            col(OrganizationFinding.resolved_at).is_not(None)
        )
    ).all():
        overlap = identities.intersection(finding.file_ids)
        if not overlap:
            continue
        saved = finding.record.get("decision_facts", {})
        saved_context = finding.record.get("decision_context", {})
        current_context = _decision_context(view, overlap)
        same = all(
            saved.get(str(i)) == _digest(_facts(view.rows[i]))
            and saved_context.get(str(i)) == current_context.get(str(i))
            for i in overlap
            if i in view.rows
        )
        if same or not new_evidence or not new_evidence.strip():
            raise ProtectedDecision(
                f"Owner decision #{finding.id} protects these files. "
                "Reconsider only with changed content/evidence and "
                "an explanation of what is new."
            )


def _flag(session: Session, finding: OrganizationFinding, view: View) -> None:
    # One durable organization finding is authoritative; entry flags provide the
    # existing queue integration. Appending preserves unrelated flag reasons.
    marker = f"[organization finding #{finding.id}]"
    block = (
        f"{marker}\nCurrent: {finding.record['current']}\n"
        f"Proposed: {finding.record['proposed']}\n"
        f"Evidence: {finding.record['evidence']}\n"
        f"[/organization finding #{finding.id}]"
    )
    entries = sorted(
        {view.rows[i]["entry_id"] for i in finding.file_ids if i in view.rows}
    )
    for identity in entries:
        existing = session.exec(
            select(ReviewFlag).where(
                col(ReviewFlag.entry_id) == identity,
                col(ReviewFlag.resolved_at).is_(None),
            )
        ).first()
        if existing is not None:
            if marker not in existing.reason:
                existing.reason = existing.reason + "\n\n" + block
                session.add(existing)
        else:
            session.add(ReviewFlag(entry_id=identity, reason=block))


def _unflag(session: Session, finding_id: int, note: str) -> None:
    start_marker = f"[organization finding #{finding_id}]"
    end_marker = f"[/organization finding #{finding_id}]"
    for flag in session.exec(
        select(ReviewFlag).where(col(ReviewFlag.resolved_at).is_(None))
    ).all():
        if start_marker not in flag.reason:
            continue
        prefix, _, tail = flag.reason.partition(start_marker)
        _, separator, suffix = tail.partition(end_marker)
        if not separator:
            continue
        remaining = (prefix.strip() + "\n\n" + suffix.strip()).strip()
        if remaining:
            flag.reason = remaining
        else:
            flag.resolved_at = utc_now()
            flag.resolution_note = note
        session.add(flag)


def _preserve_flags(
    session: Session, before: View, after: View, flags: list[ReviewFlag]
) -> None:
    """Carry unresolved questions across entry replacement during an owner fix."""
    for flag in flags:
        identities = {
            after.rows[i]["entry_id"]
            for i, row in before.rows.items()
            if row["entry_id"] == flag.entry_id and i in after.rows
        }
        for identity in identities:
            existing = session.exec(
                select(ReviewFlag).where(
                    col(ReviewFlag.entry_id) == identity,
                    col(ReviewFlag.resolved_at).is_(None),
                )
            ).first()
            if existing is None:
                session.add(ReviewFlag(entry_id=identity, reason=flag.reason))
            elif flag.reason not in existing.reason:
                existing.reason += "\n\n" + flag.reason
                session.add(existing)


def _finding(
    session: Session,
    view: View,
    group_key: str,
    *,
    status: str,
    identities: list[int],
    current: str,
    proposed: str,
    evidence: str,
    operations: list[Operation],
    results: list[dict] | None = None,
) -> OrganizationFinding:
    signature = _digest(
        {
            "file_ids": sorted(identities),
            "proposed": proposed,
            "operations": [op.model_dump() for op in operations],
        }
    )
    for existing in session.exec(
        select(OrganizationFinding).where(col(OrganizationFinding.status) == "deferred")
    ).all():
        if existing.record.get("signature") == signature and existing.record.get(
            "evidence_fingerprint"
        ) == view.evidence(identities):
            return existing
    finding = OrganizationFinding(
        group_key=group_key,
        status=status,
        file_ids=sorted(set(identities)),
        record={
            "current": current,
            "proposed": proposed,
            "evidence": evidence,
            "operations": [op.model_dump() for op in operations],
            "results": results or [],
            "signature": signature,
            "evidence_fingerprint": view.evidence(identities),
            "before": [_compact(view.rows[i]) for i in identities if i in view.rows],
        },
    )
    session.add(finding)
    session.flush()
    if status == "deferred":
        _flag(session, finding, view)
    return finding


def commit(
    session: Session,
    *,
    run_id: int,
    group_key: str,
    expected: dict[str, str],
    summary: str,
    operations: list[Operation] | None = None,
    current: str | None = None,
    proposed: str | None = None,
    evidence: str | None = None,
    recommendations: list[Recommendation] | None = None,
    new_evidence: str | None = None,
) -> dict:
    _lock(session)
    run = _run(session, run_id)
    if run.status != "active" or group_key not in run.group_keys:
        raise UsageError("Group is not in this active review run.")
    if any(r["group_key"] == group_key for r in run.results):
        raise UsageError("This group was already committed; retrieve its receipt.")
    if not summary.strip():
        raise UsageError("Provide a review summary even when no correction is needed.")
    operations = operations or []
    recommendations = recommendations or []
    if operations and not all((current, proposed, evidence)):
        raise UsageError(
            "An applied correction needs current, proposed, and evidence explanations."
        )
    if operations and not all(s and s.strip() for s in (current, proposed, evidence)):
        raise UsageError("Correction explanations must not be blank.")
    current, proposed, evidence = current or "", proposed or "", evidence or ""
    view = View.load(session, keys=list(expected))
    allowed = _expected(view, expected, group_key)
    flags = [
        ReviewFlag(entry_id=flag.entry_id, reason=flag.reason)
        for flag in session.exec(
            select(ReviewFlag).where(col(ReviewFlag.resolved_at).is_(None))
        ).all()
    ]
    for recommendation in recommendations:
        if not recommendation.file_ids or not set(recommendation.file_ids) <= allowed:
            raise UsageError("Recommendations need files from inspected groups.")
        if not all(
            s.strip()
            for s in (
                recommendation.current,
                recommendation.proposed,
                recommendation.evidence,
            )
        ):
            raise UsageError(
                "Recommendations need current, proposed, and evidence explanations."
            )
        _protect(session, view, set(recommendation.file_ids), new_evidence=new_evidence)
    applied = []
    deferred = []
    corrected_view = view
    if operations:
        try:
            with session.begin_nested():
                results, touched = _operations(session, operations, allowed, expected)
                _protect(session, view, touched, new_evidence=new_evidence)
                corrected_view = View.load(
                    session, keys=list(expected), file_ids=sorted(touched)
                )
                # Detached pack members must be assigned again within this same
                # transaction rather than accidentally becoming unfiled.
                for i in touched:
                    if (
                        i in view.rows
                        and view.rows[i]["disposition"] != "unfiled"
                        and (
                            i not in corrected_view.rows
                            or corrected_view.rows[i]["disposition"]
                            != view.rows[i]["disposition"]
                        )
                    ):
                        raise UsageError(
                            "A correction must preserve the affected files' "
                            "keep/superseded dispositions."
                        )
                _preserve_flags(session, view, corrected_view, flags)
                finding = _finding(
                    session,
                    view,
                    group_key,
                    status="applied",
                    identities=sorted(touched),
                    current=current,
                    proposed=proposed,
                    evidence=evidence,
                    operations=operations,
                    results=results,
                )
                finding.record = dict(
                    finding.record,
                    new_evidence=new_evidence,
                    after=[
                        _compact(corrected_view.rows[i])
                        for i in sorted(touched)
                        if i in corrected_view.rows
                    ],
                )
                session.add(finding)
                applied.append(finding.id)
        except (UsageError, IntegrityError) as error:
            if isinstance(error, ProtectedDecision):
                raise
            # Savepoint rolls all correction effects back, then records the complete
            # proposed correction for review in the outer transaction.
            corrected_view = view
            identities = sorted(allowed)
            finding = _finding(
                session,
                view,
                group_key,
                status="deferred",
                identities=identities,
                current=current,
                proposed=proposed,
                evidence=f"{evidence}\nCould not apply atomically: {error}",
                operations=operations,
            )
            deferred.append(finding.id)
            finding.record = dict(finding.record, new_evidence=new_evidence)
            session.add(finding)
    for recommendation in recommendations:
        finding = _finding(
            session,
            corrected_view,
            group_key,
            status="deferred",
            identities=recommendation.file_ids,
            current=recommendation.current,
            proposed=recommendation.proposed,
            evidence=recommendation.evidence,
            operations=recommendation.operations,
        )
        deferred.append(finding.id)
        finding.record = dict(finding.record, new_evidence=new_evidence)
        session.add(finding)
    coverage = session.get(OrganizationCoverage, group_key) or OrganizationCoverage(
        group_key=group_key, fingerprint="", summary=""
    )
    coverage.fingerprint = corrected_view.snapshot(group_key)["fingerprint"]
    coverage.summary = summary
    coverage.reviewed_at = utc_now()
    session.add(coverage)
    run.results = [
        *run.results,
        {
            "group_key": group_key,
            "summary": summary,
            "examined_files": view.snapshot(group_key)["file_count"],
            "applied_finding_ids": applied,
            "deferred_finding_ids": sorted(set(deferred)),
        },
    ]
    if len(run.results) == len(run.group_keys):
        run.status = "complete"
    session.add(run)
    session.flush()
    return receipt(session, run_id=run_id)


def findings(
    session: Session, *, status: str = "deferred", after_id: int = 0, limit: int = 100
) -> dict:
    if (
        status not in ("deferred", "applied", "resolved", "all")
        or not 1 <= limit <= 500
    ):
        raise UsageError("Use deferred/applied/resolved/all and limit 1..500.")
    statement = select(OrganizationFinding).where(
        col(OrganizationFinding.id) > after_id
    )
    if status == "resolved":
        statement = statement.where(col(OrganizationFinding.resolved_at).is_not(None))
    elif status != "all":
        statement = statement.where(col(OrganizationFinding.status) == status)
    records = session.exec(
        statement.order_by(col(OrganizationFinding.id)).limit(limit + 1)
    ).all()
    view = View.load(
        session,
        keys=[],
        file_ids=list({i for f in records[:limit] for i in f.file_ids}),
    )
    result = [
        {
            "finding_id": f.id,
            "group_key": f.group_key,
            "status": f.status,
            "file_ids": f.file_ids,
            "current_entry_ids": sorted(
                {view.rows[i]["entry_id"] for i in f.file_ids if i in view.rows}
            ),
            "record": f.record,
            "resolution_note": f.resolution_note,
            "resolved_at": f.resolved_at,
        }
        for f in records[:limit]
    ]
    return {
        "findings": result,
        "truncated": len(records) > limit,
        "next_after_id": records[limit - 1].id if len(records) > limit else None,
    }


def resolve(
    session: Session,
    *,
    finding_id: int,
    decision: Literal["apply", "reject", "alternative"],
    note: str,
    expected: dict[str, str] | None = None,
    operations: list[Operation] | None = None,
) -> dict:
    _lock(session)
    finding = session.get(OrganizationFinding, finding_id)
    if finding is None or finding.status != "deferred":
        raise UsageError("Choose an open organization finding.")
    if not note.strip():
        raise UsageError("Record the owner's decision and its reason in note.")
    if decision != "alternative" and operations is not None:
        raise UsageError("Custom operations require decision='alternative'.")
    view = View.load(session, keys=list(expected or {}), file_ids=finding.file_ids)
    related = {_group(row) for row in view.rows.values()}
    view = View.load(session, keys=sorted(related | set(expected or {})))
    affected = set(finding.file_ids)
    if decision != "reject":
        # Copy the reasons before update_product resolves flags or membership
        # cascades delete the old entry and its flags.
        flags = [
            ReviewFlag(entry_id=f.entry_id, reason=f.reason)
            for f in session.exec(
                select(ReviewFlag).where(col(ReviewFlag.resolved_at).is_(None))
            ).all()
        ]
        before = view
        wanted = (
            operations
            if decision == "alternative"
            else [Operation.model_validate(op) for op in finding.record["operations"]]
        )
        if not wanted:
            raise UsageError(
                "This finding has no executable proposal. "
                "Use alternative with the chosen operations."
            )
        expected = expected or {}
        if not expected:
            raise UsageError(
                "Inspect the current affected groups and pass their fingerprints."
            )
        allowed = _expected(view, expected, next(iter(expected)))
        results, touched = _operations(session, wanted, allowed, expected)
        affected.update(touched)
        view = View.load(session, keys=list(expected), file_ids=sorted(affected))
        related = {_group(row) for row in view.rows.values()}
        view = View.load(session, keys=sorted(related | set(expected)))
        _preserve_flags(session, before, view, flags)
        finding.record = dict(
            finding.record,
            resolution_operations=[op.model_dump() for op in wanted],
            resolution_results=results,
        )
    finding.status = decision
    finding.resolved_at = utc_now()
    finding.resolution_note = note.strip()
    finding.record = dict(
        finding.record,
        decision_facts={
            str(i): _digest(_facts(view.rows[i])) for i in affected if i in view.rows
        },
        decision_context=_decision_context(view, affected),
    )
    finding.file_ids = sorted(affected)
    session.add(finding)
    _unflag(session, finding_id, note)
    session.flush()
    return {
        "finding_id": finding.id,
        "decision": decision,
        "resolution_note": note,
        "physical_moves": "Catalog only; use reorganize separately.",
    }
