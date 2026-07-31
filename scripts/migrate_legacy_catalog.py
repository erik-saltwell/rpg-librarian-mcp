#!/usr/bin/env python3
"""One-time import of the legacy rpg-librarian catalog into rpg-librarian-mcp.

The legacy project (~/proj/rpg-librarian) left its catalog behind as JSON
files sitting in the library itself, at <library_root>/.catalog/:
index.json, products.json, text_fragments/<old-entry-uuid>.json, plus
backups/ and .backup/. products.json only ever identified 3 folders out of
~75k files, so there is no real product data worth recovering. The one
asset worth the trouble is text_fragments/ -- ~17k PDFs' worth of
extracted/OCR'd page text, expensive to regenerate.

This script:
  1. `scan`     -- runs the real UpdateCatalogCommand against the library
                   root, populating Entry/FileMetadata from what's on disk.
                   (Windows-style paths in the old JSON are never used --
                   only sha256 is used to bridge old fragments to new rows.)
  2. `backfill` -- for every new PDF Entry, looks up its sha256 in the old
                   index.json, and if a matching text_fragments/*.json
                   exists, imports its page text as PdfContents.sample_text
                   (under synthetic sequential page keys -- nothing
                   downstream reads real page numbers) plus a fresh,
                   cheap (no-OCR) barcode/ISBN/ISSN scan of the actual PDF.
  3. `judge`    -- runs the LLM judgment step (description/possible_system)
                   against the imported sample_text, with bounded
                   concurrency. Failures write a real Error(stage=read_pdfs)
                   row so a later plain `read_pdfs` MCP call retries them
                   the normal way.
  4. `archive`  -- (only when explicitly requested) moves the old JSON
                   files out of .catalog/ into <library_root>/_legacy-catalog/.

Every phase is safe to re-run: each skips rows it already finished, so an
interrupted run (or a deliberately capped one, via --judgment-limit) just
picks up where it left off.

Usage (run from inside the library root, using the rpg-librarian-mcp venv):

    cd ~/data/rpg
    uv run --project ~/proj/rpg-librarian-mcp python \\
        ~/proj/rpg-librarian-mcp/scripts/migrate_legacy_catalog.py

    # judgment calls hit a paid LLM API -- cap how many run in one go:
    uv run --project ~/proj/rpg-librarian-mcp python \\
        ~/proj/rpg-librarian-mcp/scripts/migrate_legacy_catalog.py --judgment-limit 500

    # once you're happy with the result, archive the old files:
    uv run --project ~/proj/rpg-librarian-mcp python \\
        ~/proj/rpg-librarian-mcp/scripts/migrate_legacy_catalog.py --phase archive
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import cast

import fitz
import litellm
from fastmcp import Context
from sqlmodel import col, select

from rpg_librarian_mcp.catalog import Catalog, load_env
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.isbn import isbn, issn
from rpg_librarian_mcp.llm.pdf_judgment import PdfLlmJudgment, judge_pdf_contents
from rpg_librarian_mcp.metadata.extractors.pdf_extractor import PdfExtractor
from rpg_librarian_mcp.model import (
    Entry,
    Error,
    MediaType,
    PdfContents,
    ProcessingStage,
)
from rpg_librarian_mcp.tools.barcode import find_isbn_or_issn_barcode
from rpg_librarian_mcp.tools.text_extraction import barcode_sample_pages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_legacy_catalog")

LEGACY_ARTIFACTS = ["index.json", "products.json", "backups", ".backup"]
LEGACY_TEXT_FRAGMENTS_DIR = "text_fragments"
LEGACY_DIRNAME = "_legacy-catalog"
FATAL_LLM_EXCEPTIONS = (litellm.AuthenticationError, litellm.RateLimitError)


# --------------------------------------------------------------------------
# Progress display
# --------------------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


class ProgressBar:
    """A single, in-place-updating status line on stderr.

    Redrawn on a time throttle (not every call) so a tight loop doesn't
    spend its time repainting the terminal. Log lines from `log.info` etc.
    print above it just fine since they go to a fresh line and this bar
    always starts its own line with `\\r`.
    """

    _MIN_REDRAW_INTERVAL = 0.2

    def __init__(self, total: int, label: str) -> None:
        self.total = total
        self.label = label
        self.count = 0
        self._start = time.monotonic()
        self._last_redraw = 0.0

    def set(self, count: int) -> None:
        self.count = count
        self._maybe_render()

    def advance(self, n: int = 1) -> None:
        self.count += n
        self._maybe_render()

    def _maybe_render(self) -> None:
        now = time.monotonic()
        done = self.total > 0 and self.count >= self.total
        if not done and now - self._last_redraw < self._MIN_REDRAW_INTERVAL:
            return
        self._last_redraw = now
        self._render()

    def _render(self) -> None:
        elapsed = time.monotonic() - self._start
        rate = self.count / elapsed if elapsed > 0 else 0.0
        percent = (self.count / self.total * 100) if self.total else 100.0
        remaining = max(0, self.total - self.count)
        eta = remaining / rate if rate > 0 else 0.0
        sys.stderr.write(
            f"\r{self.label}: {self.count}/{self.total} ({percent:5.1f}%) "
            f"{rate:5.1f}/s eta {_format_duration(eta):<8}"
        )
        sys.stderr.flush()

    def close(self) -> None:
        self._render()
        sys.stderr.write("\n")
        sys.stderr.flush()


# --------------------------------------------------------------------------
# Legacy data loading
# --------------------------------------------------------------------------


def _load_legacy_index(catalog_dir: Path) -> dict:
    index_path = catalog_dir / "index.json"
    with index_path.open(encoding="utf-8") as f:
        return json.load(f)


def _sha256_to_legacy_id(legacy_index: dict) -> dict[str, str]:
    """sha256 -> legacy entry id, PDFs only.

    First entry wins on a hash collision -- legacy duplicates have
    identical content, so it doesn't matter which one supplies the text.
    """
    mapping: dict[str, str] = {}
    for entry in legacy_index["entries"]:
        if entry["media_type"] != "pdf":
            continue
        sha = entry["file_data"]["sha256"]
        mapping.setdefault(sha, entry["id"])
    return mapping


def _fragment_sample_text(fragment: dict) -> tuple[str, str]:
    """(sample_text JSON blob, concatenated plain text) from a legacy fragment.

    Legacy fragments store page text as a plain ordered list with no real
    page numbers, and the legacy sampling window doesn't match the new
    convention anyway -- synthetic sequential keys are used instead. Nothing
    downstream (LLM prompt, classify_content_role) reads real page numbers.
    """
    pages = {
        str(index + 1): page.get("text") or ""
        for index, page in enumerate(fragment.get("pages", []))
    }
    content = "\n".join(pages.values())
    return json.dumps({"pages": pages}), content


# --------------------------------------------------------------------------
# Phase 1: scan (delegates to the real update_catalog logic)
# --------------------------------------------------------------------------


class _ScanProgressContext:
    """Duck-types just enough of fastmcp's Context for UpdateCatalogCommand:
    it only ever awaits `report_progress(current, total, message)`."""

    def __init__(self) -> None:
        self._bar: ProgressBar | None = None

    async def report_progress(
        self, current: int, total: int, message: str | None = None
    ) -> None:
        if self._bar is None:
            self._bar = ProgressBar(total, "scan")
        self._bar.total = total
        self._bar.set(current)
        if current >= total and self._bar is not None:
            self._bar.close()
            self._bar = None


def run_scan(catalog: Catalog) -> None:
    log.info("Scanning %s ...", catalog.library_root)
    command = UpdateCatalogCommand(catalog)
    result = asyncio.run(
        command.process(
            catalog.library_root, True, False, cast(Context, _ScanProgressContext())
        )
    )
    log.info(
        "Scan complete: scanned=%d processed=%d skipped=%d removed=%d errored=%d",
        result.scanned,
        result.successfully_processed,
        result.skipped,
        result.removed,
        result.errored,
    )
    for error in result.errors:
        log.warning("scan error: %s: %s", error.path, error.reason)


# --------------------------------------------------------------------------
# Phase 2: backfill (sample_text + fresh barcode/ISBN/ISSN)
# --------------------------------------------------------------------------


def _extract_isbn_issn(
    doc: fitz.Document, content: str, file_path: Path
) -> tuple[str | None, str | None, str | None]:
    """Mirrors ReadPdfsCommand's non-OCR extraction chain: barcode, then
    text-based regex, then embedded PDF metadata fields."""
    barcode_match = find_isbn_or_issn_barcode(doc, barcode_sample_pages(doc.page_count))
    pdf_isbn = barcode_match.isbn if barcode_match else None
    pdf_issn = barcode_match.issn if barcode_match else None
    if pdf_isbn is None and pdf_issn is None:
        pdf_isbn = isbn.extract(content)
    if pdf_isbn is None and pdf_issn is None:
        pdf_issn = issn.extract(content)
    if pdf_isbn is None and pdf_issn is None:
        fallback = PdfExtractor(file_path)
        pdf_isbn = fallback.extract_isbn()
        if pdf_isbn is None:
            pdf_issn = fallback.extract_issn()
    barcode_text = barcode_match.barcode_text if barcode_match else None
    return barcode_text, pdf_isbn, pdf_issn


def run_backfill(catalog: Catalog) -> None:
    legacy_index = _load_legacy_index(catalog.catalog_dir)
    sha_to_legacy_id = _sha256_to_legacy_id(legacy_index)
    fragments_dir = catalog.catalog_dir / LEGACY_TEXT_FRAGMENTS_DIR
    log.info("Loaded legacy index: %d PDF entries with sha256", len(sha_to_legacy_id))

    matched = unmatched = already_done = errored = skipped_encrypted = 0

    with session_scope(catalog) as session:
        pdf_entries = session.exec(
            select(Entry).where(Entry.media_type == MediaType.pdf)
        ).all()
        log.info("%d PDF entries in the new catalog", len(pdf_entries))

        bar = ProgressBar(len(pdf_entries), "backfill")
        for entry in pdf_entries:
            bar.advance()
            if session.get(PdfContents, entry.id) is not None:
                already_done += 1
                continue

            legacy_id = sha_to_legacy_id.get(entry.sha256)
            if legacy_id is None:
                unmatched += 1
                continue

            fragment_path = fragments_dir / f"{legacy_id}.json"
            if not fragment_path.exists():
                unmatched += 1
                continue

            with fragment_path.open(encoding="utf-8") as f:
                fragment = json.load(f)
            sample_text_blob, content = _fragment_sample_text(fragment)

            file_path = catalog.to_absolute(entry.path)
            try:
                doc = fitz.open(file_path)
                try:
                    if doc.needs_pass:
                        # Password-protected: the real read_pdfs also skips
                        # these entirely (no PdfContents row at all), so a
                        # later real read_pdfs call would treat this exactly
                        # like a fresh, never-processed PDF.
                        skipped_encrypted += 1
                        continue
                    barcode_text, pdf_isbn, pdf_issn = _extract_isbn_issn(
                        doc, content, file_path
                    )
                finally:
                    doc.close()
            except Exception as exc:
                errored += 1
                log.warning("backfill error on %s: %s", entry.path, exc)
                error_row = Error(
                    entry_id=entry.id,
                    stage=ProcessingStage.read_pdfs,
                    error_text=str(exc),
                )
                session.merge(error_row)
                session.commit()
                continue

            pdf_contents = PdfContents(
                entry_id=entry.id,
                barcode=barcode_text,
                isbn=pdf_isbn,
                issn=pdf_issn,
                sample_text=sample_text_blob,
            )
            session.merge(pdf_contents)
            session.commit()
            matched += 1

        bar.close()

    log.info(
        "Backfill complete: matched=%d already_done=%d unmatched=%d "
        "encrypted_skipped=%d errored=%d",
        matched,
        already_done,
        unmatched,
        skipped_encrypted,
        errored,
    )


# --------------------------------------------------------------------------
# Phase 3: judge (LLM description/possible_system)
# --------------------------------------------------------------------------


def _judgment_candidates(
    catalog: Catalog, limit: int | None
) -> list[tuple[uuid.UUID, str]]:
    with session_scope(catalog) as session:
        rows = session.exec(
            select(PdfContents).where(
                col(PdfContents.description).is_(None),
                col(PdfContents.sample_text).is_not(None),
            )
        ).all()
    candidates: list[tuple[uuid.UUID, str]] = []
    for row in rows:
        if row.entry_id is None or not row.sample_text:
            continue
        pages = json.loads(row.sample_text).get("pages")
        if pages and "".join(pages.values()).strip():
            candidates.append((row.entry_id, row.sample_text))
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def _judge_one(
    entry_id: uuid.UUID, sample_text: str
) -> tuple[uuid.UUID, PdfLlmJudgment]:
    return entry_id, judge_pdf_contents(sample_text)


def run_judge(catalog: Catalog, workers: int, limit: int | None) -> None:
    candidates = _judgment_candidates(catalog, limit)
    log.info(
        "%d PDFs need LLM judgment%s",
        len(candidates),
        " (capped)" if limit else "",
    )
    if not candidates:
        return

    judged = errored = 0
    fatal = False
    bar = ProgressBar(len(candidates), "judge")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_judge_one, entry_id, sample_text): entry_id
            for entry_id, sample_text in candidates
        }
        for future in as_completed(futures):
            entry_id = futures[future]
            try:
                _, judgment = future.result()
            except FATAL_LLM_EXCEPTIONS as exc:
                bar.close()
                log.error("Fatal LLM error, stopping: %s", exc)
                fatal = True
                for pending in futures:
                    pending.cancel()
                break
            except Exception as exc:
                errored += 1
                bar.advance()
                log.warning("judgment error on entry %s: %s", entry_id, exc)
                with session_scope(catalog) as session:
                    error_row = Error(
                        entry_id=entry_id,
                        stage=ProcessingStage.read_pdfs,
                        error_text=str(exc),
                    )
                    session.merge(error_row)
                    session.commit()
                continue

            with session_scope(catalog) as session:
                pdf_contents = session.get(PdfContents, entry_id)
                if pdf_contents is not None:
                    pdf_contents.description = judgment.description
                    pdf_contents.possible_system = judgment.possible_system
                    session.add(pdf_contents)
                    session.commit()
            judged += 1
            bar.advance()
        else:
            bar.close()

    log.info(
        "Judgment complete: judged=%d errored=%d%s",
        judged,
        errored,
        " (stopped early on fatal error)" if fatal else "",
    )


# --------------------------------------------------------------------------
# Phase 4: archive (explicit only)
# --------------------------------------------------------------------------


def run_archive(catalog: Catalog) -> None:
    legacy_dir = catalog.library_root / LEGACY_DIRNAME
    legacy_dir.mkdir(exist_ok=True)

    moved: list[str] = []
    for name in [*LEGACY_ARTIFACTS, LEGACY_TEXT_FRAGMENTS_DIR]:
        source = catalog.catalog_dir / name
        if not source.exists():
            continue
        destination = legacy_dir / name
        if destination.exists():
            log.warning("skipping %s: already present at %s", name, destination)
            continue
        shutil.move(str(source), str(destination))
        moved.append(name)

    log.info("Archived to %s: %s", legacy_dir, moved or "(nothing found)")


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=["all", "scan", "backfill", "judge", "archive"],
        default="all",
        help="Which phase to run. 'all' runs scan+backfill+judge but never "
        "archive -- archive is always explicit.",
    )
    parser.add_argument(
        "--workers", type=int, default=6, help="Concurrent LLM judgment calls."
    )
    parser.add_argument(
        "--judgment-limit",
        type=int,
        default=None,
        help="Cap how many PDFs get judged in this run (cost control). "
        "Re-run the script to pick up the rest.",
    )
    args = parser.parse_args()

    load_env()
    catalog = Catalog.from_cwd()
    # rpg-librarian-mcp's own dev .env can carry a DATABASE_URL pointing at
    # its test sandbox. alembic's env.py always prefers DATABASE_URL over
    # whatever db_path db.py asks it to migrate -- and env.py calls
    # load_env() again on every migration run, which repopulates
    # DATABASE_URL from that same .env (via override=False) the instant
    # it's unset. Setting it ourselves, to the real target, is what
    # actually sticks: override=False then leaves our value alone.
    os.environ["DATABASE_URL"] = f"sqlite:///{catalog.db_path}"
    log.info("Library root: %s", catalog.library_root)

    if args.phase in ("all", "scan"):
        run_scan(catalog)
    if args.phase in ("all", "backfill"):
        run_backfill(catalog)
    if args.phase in ("all", "judge"):
        run_judge(catalog, args.workers, args.judgment_limit)
    if args.phase == "archive":
        run_archive(catalog)


if __name__ == "__main__":
    main()
