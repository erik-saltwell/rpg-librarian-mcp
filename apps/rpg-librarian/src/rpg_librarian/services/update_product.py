"""`update_product`: the one writer. Records the LLM's judgment in the catalog.

One call is one transaction: every check runs before anything is kept, and any
failure raises `UsageError` so the caller rolls the whole call back, naming what
failed. Partial success would leave the LLM guessing what landed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlmodel import Session, col, select

from ..errors import UsageError
from ..model import (
    Disposition,
    File,
    Product,
    ProductLine,
    ProductLineAlias,
    ProductType,
    ReviewFlag,
)
from ..paths import folder_key, kept_file_count, sanitize_name
from .names import clean_name, closest_names, near_matches, normalize_name

MAX_FILES_PER_CALL = 500
# What the LLM may write. `duplicate` is written only by `scan`.
WRITABLE_DISPOSITIONS = (
    Disposition.keep,
    Disposition.superseded,
    Disposition.discard,
    Disposition.unfiled,
)
PRODUCT_METADATA_FIELDS = ("publisher", "year", "artists", "description")


@dataclass
class UpdateProductRequest:
    file_ids: list[int]
    disposition: Disposition | None = None
    product_type: str | None = None
    product_line: str | None = None
    product: str | None = None
    product_metadata: dict[str, str | None] | None = None
    create_line: bool = False
    create_type: bool = False
    aliases: list[str] = field(default_factory=list)
    review_flag: str | None = None
    note: str | None = None


@dataclass
class _Outcome:
    warnings: list[str] = field(default_factory=list)
    created_type: bool = False
    created_line: bool = False
    created_product: bool = False
    added_aliases: list[str] = field(default_factory=list)


def update_product(session: Session, request: UpdateProductRequest) -> dict[str, Any]:
    """Apply one judgment to some files, or raise `UsageError` and change nothing."""
    ids = list(dict.fromkeys(request.file_ids))
    coordinates = _validate_request(request, ids)
    files = _load_files(session, ids)

    outcome = _Outcome()
    product: Product | None = None
    line: ProductLine | None = None
    product_type: ProductType | None = None
    if coordinates:
        assert request.product_type and request.product_line and request.product
        product_type = _resolve_type(session, request, outcome)
        line = _resolve_line(session, request, product_type, outcome)
        product = _resolve_product(session, request.product, line, outcome)
        _apply_product_metadata(product, request.product_metadata)
        session.add(product)
        session.flush()

    final = (
        Disposition.unfiled if request.review_flag is not None else request.disposition
    )
    assert final is not None
    resolved_flags = 0
    now = datetime.now(UTC)
    for file in files:
        if request.review_flag is not None:
            _open_flag(session, file, request.review_flag)
            continue
        file.disposition = final
        if final is Disposition.unfiled:
            file.product_id = None
        elif product is not None:
            file.product_id = product.id
        session.add(file)
        if final is not Disposition.unfiled:
            resolved_flags += _resolve_flags(session, file, request.note, now)
    session.flush()

    result: dict[str, Any] = {
        "updated_file_ids": ids,
        "disposition": None if request.review_flag is not None else final.value,
        "review_flag_opened": request.review_flag is not None,
        "review_flags_resolved": resolved_flags,
        "warnings": outcome.warnings,
        "created": {
            "type": outcome.created_type,
            "line": outcome.created_line,
            "product": outcome.created_product,
            "aliases": outcome.added_aliases,
        },
        "product": None,
    }
    if product is not None and line is not None and product_type is not None:
        assert product.id is not None
        kept = kept_file_count(session, product.id)
        parts = [sanitize_name(product_type.name), sanitize_name(line.name)]
        if kept > 1:
            parts.append(sanitize_name(product.name))
        result["product"] = {
            "id": product.id,
            "name": product.name,
            "line": {"id": line.id, "name": line.name},
            "type": {"id": product_type.id, "name": product_type.name},
            "kept_files": kept,
            "target_folder": str(PurePosixPath(*parts)),
        }
    return result


# -- validation ---------------------------------------------------------------


def _validate_request(request: UpdateProductRequest, ids: list[int]) -> bool:
    """Reject an impossible request. Returns whether product coordinates are given."""
    if not ids:
        raise UsageError("file_ids is empty.")
    if len(ids) > MAX_FILES_PER_CALL:
        raise UsageError(
            f"Too many files ({len(ids)}); at most {MAX_FILES_PER_CALL} per call."
        )

    given = [
        value
        for value in (request.product_type, request.product_line, request.product)
        if value is not None
    ]
    if any(not clean_name(value) for value in given):
        raise UsageError("product_type, product_line, and product cannot be blank.")
    coordinates = len(given) == 3
    if given and not coordinates:
        raise UsageError(
            "Give product_type, product_line, and product together, or none of them."
        )

    if request.review_flag is not None:
        if not request.review_flag.strip():
            raise UsageError("review_flag needs a reason.")
        if request.disposition not in (None, Disposition.unfiled):
            raise UsageError(
                "review_flag defers a decision and cannot be combined with a "
                f"disposition of {request.disposition.value!r}. Drop one of them."
            )
        if coordinates or request.aliases or request.product_metadata:
            raise UsageError(
                "review_flag defers a decision, so it takes no product details."
            )
        return False

    if request.disposition is None:
        raise UsageError("Give a disposition, or a review_flag to defer.")
    if request.disposition not in WRITABLE_DISPOSITIONS:
        raise UsageError(
            f"Disposition {request.disposition.value!r} cannot be set here. "
            "Use keep, superseded, discard, or unfiled."
        )
    if request.disposition is Disposition.keep and not coordinates:
        raise UsageError(
            "keep needs product_type, product_line, and product: a kept file "
            "must belong to a product."
        )
    discarding = request.disposition in (Disposition.discard, Disposition.unfiled)
    if discarding and coordinates:
        raise UsageError(
            f"{request.disposition.value} takes no product_type, product_line, "
            "or product."
        )
    if not coordinates and (
        request.aliases
        or request.product_metadata
        or request.create_line
        or request.create_type
    ):
        raise UsageError(
            "aliases, product_metadata, create_line, and create_type apply only "
            "when product_type, product_line, and product are given."
        )
    unknown = set(request.product_metadata or {}) - set(PRODUCT_METADATA_FIELDS)
    if unknown:
        raise UsageError(
            f"Unknown product_metadata field(s) {sorted(unknown)}; "
            f"allowed: {list(PRODUCT_METADATA_FIELDS)}."
        )
    return coordinates


def _load_files(session: Session, ids: list[int]) -> list[File]:
    files = {
        file.id: file
        for file in session.exec(select(File).where(col(File.id).in_(ids))).all()
    }
    problems = [f"file {i}: no such file" for i in ids if i not in files]
    for i in ids:
        file = files.get(i)
        if file is None:
            continue
        if file.disposition is Disposition.duplicate:
            original = (
                f" of file {file.duplicate_of_id}" if file.duplicate_of_id else ""
            )
            problems.append(
                f"file {i}: an automatic duplicate{original}; file the original instead"
            )
        elif file.missing_since is not None:
            problems.append(
                f"file {i}: missing from the share since "
                f"{file.missing_since:%Y-%m-%d}; run `scan` again first"
            )
    if problems:
        raise UsageError("Nothing was changed. " + "; ".join(problems) + ".")
    return [files[i] for i in ids]


# -- resolving coordinates ----------------------------------------------------


def _resolve_type(
    session: Session, request: UpdateProductRequest, outcome: _Outcome
) -> ProductType:
    assert request.product_type
    types = list(session.exec(select(ProductType)).all())
    wanted = normalize_name(request.product_type)
    for candidate in types:
        if normalize_name(candidate.name) == wanted:
            return candidate

    names = [t.name for t in types]
    if not request.create_type:
        closest = closest_names(request.product_type, names)
        raise UsageError(
            f"Unknown product type {request.product_type!r}. "
            f"Closest existing: {closest or 'none'}. "
            f"All types: {names}. A type is a top-level folder on the share; "
            "pass create_type=true only if a new one is really wanted."
        )
    _reject_folder_collision(request.product_type, names, "product type")
    created = ProductType(name=clean_name(request.product_type))
    session.add(created)
    session.flush()
    outcome.created_type = True
    return created


def _resolve_line(
    session: Session,
    request: UpdateProductRequest,
    product_type: ProductType,
    outcome: _Outcome,
) -> ProductLine:
    assert request.product_line
    assert product_type.id is not None
    lines = list(
        session.exec(
            select(ProductLine).where(
                col(ProductLine.product_type_id) == product_type.id
            )
        ).all()
    )
    aliases_by_line: dict[int, list[str]] = {}
    if lines:
        for alias in session.exec(
            select(ProductLineAlias).where(
                col(ProductLineAlias.product_line_id).in_(
                    [line.id for line in lines if line.id is not None]
                )
            )
        ).all():
            aliases_by_line.setdefault(alias.product_line_id, []).append(alias.alias)

    wanted = normalize_name(request.product_line)
    found = next(
        (
            line
            for line in lines
            if line.id is not None
            and wanted
            in {
                normalize_name(line.name),
                *(normalize_name(a) for a in aliases_by_line.get(line.id, [])),
            }
        ),
        None,
    )

    if found is None:
        if not (request.create_line or outcome.created_type):
            known = [line.name for line in lines]
            known += [a for names in aliases_by_line.values() for a in names]
            elsewhere = _lines_named_elsewhere(
                session, request.product_line, product_type
            )
            hint = (
                f" A line with that name exists under type {elsewhere}."
                if elsewhere
                else ""
            )
            raise UsageError(
                f"Unknown product line {request.product_line!r} under type "
                f"{product_type.name!r}. Closest existing: "
                f"{closest_names(request.product_line, known) or 'none'}.{hint} "
                "Search with list_product_lines first; pass create_line=true only "
                "if it really is a new line."
            )
        _reject_folder_collision(
            request.product_line, [line.name for line in lines], "product line"
        )
        found = ProductLine(
            product_type_id=product_type.id, name=clean_name(request.product_line)
        )
        session.add(found)
        session.flush()
        outcome.created_line = True
        assert found.id is not None
        aliases_by_line[found.id] = []

    _add_aliases(session, request.aliases, found, lines, aliases_by_line, outcome)
    return found


def _lines_named_elsewhere(
    session: Session, name: str, product_type: ProductType
) -> str | None:
    rows = session.exec(
        select(ProductLine, ProductType)
        .join(ProductType, col(ProductType.id) == col(ProductLine.product_type_id))
        .where(col(ProductLine.product_type_id) != product_type.id)
    ).all()
    wanted = normalize_name(name)
    for line, other_type in rows:
        if normalize_name(line.name) == wanted:
            return repr(other_type.name)
    return None


def _add_aliases(
    session: Session,
    requested: list[str],
    line: ProductLine,
    lines: list[ProductLine],
    aliases_by_line: dict[int, list[str]],
    outcome: _Outcome,
) -> None:
    assert line.id is not None
    own = {
        normalize_name(line.name),
        *(normalize_name(a) for a in aliases_by_line.get(line.id, [])),
    }
    taken: dict[str, str] = {}
    for other in lines:
        if other.id == line.id or other.id is None:
            continue
        taken[normalize_name(other.name)] = other.name
        for alias in aliases_by_line.get(other.id, []):
            taken[normalize_name(alias)] = other.name

    for alias in requested:
        cleaned = clean_name(alias)
        key = normalize_name(alias)
        if not cleaned or key in own:
            continue
        if key in taken:
            raise UsageError(
                f"Alias {alias!r} is already a name or alias of line {taken[key]!r} "
                "in this type."
            )
        session.add(ProductLineAlias(product_line_id=line.id, alias=cleaned))
        own.add(key)
        outcome.added_aliases.append(cleaned)


def _resolve_product(
    session: Session, name: str, line: ProductLine, outcome: _Outcome
) -> Product:
    assert line.id is not None
    products = list(
        session.exec(
            select(Product).where(col(Product.product_line_id) == line.id)
        ).all()
    )
    wanted = normalize_name(name)
    for candidate in products:
        if normalize_name(candidate.name) == wanted:
            return candidate

    names = [p.name for p in products]
    _reject_folder_collision(name, names, "product")
    similar = near_matches(name, names)
    if similar:
        outcome.warnings.append(
            f"Created product {clean_name(name)!r}, which looks close to existing "
            f"{similar} in this line. If it is the same product, re-file with the "
            "existing name."
        )
    created = Product(product_line_id=line.id, name=clean_name(name))
    session.add(created)
    session.flush()
    outcome.created_product = True
    return created


def _reject_folder_collision(name: str, existing: list[str], kind: str) -> None:
    """Two names that sanitize to one folder would silently merge on the share."""
    key = folder_key(name)
    for other in existing:
        if folder_key(other) == key and normalize_name(other) != normalize_name(name):
            raise UsageError(
                f"The {kind} name {name!r} would share a folder with the existing "
                f"{kind} {other!r} (illegal characters are replaced when filing). "
                "Use that name, or pick a clearly different one."
            )


def _apply_product_metadata(
    product: Product, metadata: dict[str, str | None] | None
) -> None:
    for key, value in (metadata or {}).items():
        if value is not None and value.strip():
            setattr(product, key, value.strip())


# -- review flags -------------------------------------------------------------


def _open_flag(session: Session, file: File, reason: str) -> None:
    existing = session.exec(
        select(ReviewFlag)
        .where(col(ReviewFlag.file_id) == file.id)
        .where(col(ReviewFlag.resolved_at).is_(None))
    ).first()
    if existing is not None:
        existing.reason = reason.strip()
        session.add(existing)
    else:
        assert file.id is not None
        session.add(ReviewFlag(file_id=file.id, reason=reason.strip()))


def _resolve_flags(
    session: Session, file: File, note: str | None, now: datetime
) -> int:
    open_flags = session.exec(
        select(ReviewFlag)
        .where(col(ReviewFlag.file_id) == file.id)
        .where(col(ReviewFlag.resolved_at).is_(None))
    ).all()
    for flag in open_flags:
        flag.resolved_at = now
        flag.resolution_note = note.strip() if note and note.strip() else None
        session.add(flag)
    return len(open_flags)
