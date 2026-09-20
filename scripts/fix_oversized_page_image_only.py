#!/usr/bin/env python3
"""One-time backfill for the oversized-page rules in `is_likely_image_only`.

`is_likely_image_only` (tools/text_extraction.py) now also flags a document
as image-only -- without paying for a render+OCR pass -- when every page is
bigger than 20" on either side and has no real text layer: a single poster/
city-map page, or a multi-sheet map pack. Existing `PdfMetadata` rows
computed before that change can be wrong -- a `likely_image_only=False` row
for such a document never got the size check applied.

This script re-evaluates only that one condition (`_all_pages_oversized_and_
textless`) against already-cataloged PDFs and flips `likely_image_only`
where it now disagrees. It never re-renders or re-OCRs anything: the check
only reads each page's size and text layer.

Candidates are `PdfMetadata` rows where:
  - has_extractable_text == False (a real text layer on any sampled page
    already forces False under both the old and new logic -- unaffected,
    so skipped as a cheap prefilter; the per-file check below still scans
    every page, not just the sampled ones, to confirm)
  - likely_image_only is not already True (nothing to flip)

Usage (run from inside the library root, using the rpg-librarian-mcp venv):

    cd ~/data/rpg
    uv run --project ~/proj/rpg-librarian-mcp python \\
        ~/proj/rpg-librarian-mcp/scripts/fix_oversized_page_image_only.py

    # see what would change without writing anything:
    uv run --project ~/proj/rpg-librarian-mcp python \\
        ~/proj/rpg-librarian-mcp/scripts/fix_oversized_page_image_only.py --dry-run
"""

from __future__ import annotations

import argparse
import logging

from sqlmodel import col, select

from rpg_librarian_mcp.catalog import Catalog, load_env
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry, PdfMetadata
from rpg_librarian_tools.pdf import ImageAssessmentStatus, assess_images

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fix_oversized_page_image_only")


def run(catalog: Catalog, dry_run: bool) -> None:
    checked = updated = already_true = missing_file = errored = 0

    with session_scope(catalog) as session:
        candidates = session.exec(
            select(PdfMetadata).where(
                col(PdfMetadata.has_extractable_text).is_(False),
                col(PdfMetadata.likely_image_only).is_not(True),
            )
        ).all()
        log.info("%d textless PDFs to re-check", len(candidates))

        for pdf_metadata in candidates:
            checked += 1
            entry = session.get(Entry, pdf_metadata.entry_id)
            if entry is None:
                continue

            file_path = catalog.to_absolute(entry.path)
            if not file_path.exists():
                missing_file += 1
                log.warning("missing file for entry %s: %s", entry.id, file_path)
                continue

            try:
                oversized = (
                    assess_images(file_path).status is ImageAssessmentStatus.IMAGE_ONLY
                )
            except Exception as exc:
                errored += 1
                log.warning("error reading %s: %s", file_path, exc)
                continue

            if not oversized:
                continue

            if pdf_metadata.likely_image_only is True:
                already_true += 1
                continue

            updated += 1
            log.info("oversized -> likely_image_only=True: %s", entry.path)
            if not dry_run:
                pdf_metadata.likely_image_only = True
                session.add(pdf_metadata)
                session.commit()

    log.info(
        "Done: checked=%d updated=%d already_true=%d missing_file=%d errored=%d%s",
        checked,
        updated,
        already_true,
        missing_file,
        errored,
        " (dry run, nothing written)" if dry_run else "",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    args = parser.parse_args()

    load_env()
    catalog = Catalog.from_cwd()
    log.info("Library root: %s", catalog.library_root)
    run(catalog, args.dry_run)


if __name__ == "__main__":
    main()
