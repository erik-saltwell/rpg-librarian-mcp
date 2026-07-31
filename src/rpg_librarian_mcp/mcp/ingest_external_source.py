"""ingest_external_source -- stage new content from outside the library."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import select

from ..catalog import Catalog
from ..db import session_scope
from ..model import Entry
from ..tools.sha256 import generate_sha256

REPORT_FILENAME = "_ingest_report.md"


def _validate_name(name: str) -> None:
    if not name.strip():
        raise ValueError("name must not be empty")
    if Path(name).name != name:
        raise ValueError("name must not contain path separators")


def _library_hashes(catalog: Catalog) -> dict[str, str]:
    """sha256 -> library-relative path for every cataloged Entry.

    Selects full `Entry` rows rather than individual columns -- same
    Python-side-over-SQL-tuple precedent as `summarize_directories`'
    aggregation (`tools_spec.md`), which exists because `ty` can't resolve
    `sqlmodel`'s multi-column `select()` overloads.
    """
    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()
    hashes: dict[str, str] = {}
    for entry in entries:
        hashes.setdefault(entry.sha256, str(entry.path))
    return hashes


def _hash_tree(root: Path) -> dict[str, Path]:
    """sha256 -> path relative to `root`, for every file already under it."""
    hashes: dict[str, Path] = {}
    if not root.exists():
        return hashes
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        hashes.setdefault(generate_sha256(file_path), file_path.relative_to(root))
    return hashes


def _write_report(
    report_path: Path,
    name: str,
    copied: list[dict[str, str]],
    skipped: list[dict[str, str]],
) -> None:
    today = datetime.now(UTC).date().isoformat()
    lines = [f"# Ingest report — {name} ({today})", ""]
    lines.append(f"## Copied ({len(copied)})")
    for item in copied:
        lines.append(f"- {item['path']} -> {item['destination']}")
    lines.append("")
    lines.append(f"## Skipped as duplicate ({len(skipped)})")
    for item in skipped:
        lines.append(f"- {item['path']} -> {item['matched']}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ingest_external_source(
    catalog: Catalog, source_path: Path, name: str
) -> dict[str, object]:
    """Copy new (non-duplicate) content from `source_path` into
    `_inbox/<name>/`, deduping by sha256 against both the library and any
    content already staged there from a prior run of the same source."""
    _validate_name(name)

    if not source_path.is_absolute():
        raise ValueError(f"{source_path} must be an absolute path")
    if not source_path.exists():
        raise ValueError(f"{source_path} does not exist")

    try:
        catalog.to_relative(source_path)
    except ValueError:
        pass
    else:
        raise ValueError(
            f"{source_path} is inside the library root -- it is already "
            "cataloged content, use update_catalog directly instead"
        )

    inbox_relative = Path("_inbox") / name
    inbox_absolute = catalog.to_absolute(inbox_relative)

    library_hashes = _library_hashes(catalog)
    staged_hashes = _hash_tree(inbox_absolute)

    copied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for file_path in sorted(source_path.rglob("*")):
        if not file_path.is_file():
            continue

        relative = file_path.relative_to(source_path)
        digest = generate_sha256(file_path)

        library_match = library_hashes.get(digest)
        if library_match is not None:
            skipped.append({"path": str(relative), "matched": library_match})
            continue

        staged_match = staged_hashes.get(digest)
        if staged_match is not None:
            skipped.append(
                {
                    "path": str(relative),
                    "matched": str(inbox_relative / staged_match),
                }
            )
            continue

        destination = inbox_absolute / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, destination)
        copied.append(
            {"path": str(relative), "destination": str(inbox_relative / relative)}
        )

    inbox_absolute.mkdir(parents=True, exist_ok=True)
    report_path = inbox_absolute / REPORT_FILENAME
    _write_report(report_path, name, copied, skipped)

    return {
        "source_path": str(source_path),
        "name": name,
        "scanned": len(copied) + len(skipped),
        "copied": len(copied),
        "skipped_duplicate": len(skipped),
        "report_path": str(catalog.to_relative(report_path)),
    }


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="ingest_external_source")
    def ingest_external_source_tool(source_path: Path, name: str) -> dict[str, object]:
        """Copy new (non-duplicate) content from an external path into
        `_inbox/<name>/`, deduping by content hash against both the
        library and any previously staged content under the same name.

        `source_path` must be an absolute path outside the library root.
        Every file's sha256 is compared against the library's cataloged
        entries and against anything already staged at `_inbox/<name>/`
        from a prior run; only genuinely new content is copied, preserving
        `source_path`'s internal folder structure. A full manifest (every
        copied and skipped file, with what each skip matched) is written
        to `_inbox/<name>/_ingest_report.md`; this call returns only
        summary counts and that report's path. Once content is staged, run
        the normal pipeline (update_catalog, read_pdfs, update_product,
        classify_content_role) against `_inbox/<name>/` to integrate it.
        """
        return ingest_external_source(catalog, source_path, name)
