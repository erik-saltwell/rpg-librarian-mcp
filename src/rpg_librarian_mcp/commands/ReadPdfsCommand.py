from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import fitz
import litellm
from fastmcp import Context
from sqlmodel import Session

from ..isbn import isbn, issn
from ..llm.pdf_judgment import judge_pdf_contents
from ..metadata.extractors.pdf_extractor import PdfExtractor
from ..model import Entry, Error, MediaType, PdfContents
from ..tools.barcode import find_isbn_or_issn_barcode
from ..tools.ocr import check_tesseract_available
from ..tools.text_extraction import (
    barcode_sample_pages,
    extract_page_texts,
    sample_text_json,
    text_sample_pages,
)
from .UpdateBaseCommand import UpdateBaseCommand, UpdateResult


class ReadPdfsCommand(UpdateBaseCommand):
    fatal_exceptions: ClassVar[tuple[type[BaseException], ...]] = (
        litellm.AuthenticationError,
        litellm.RateLimitError,
    )

    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        ctx: Context,
    ) -> UpdateResult:
        """Same as the base `process`, plus a one-time Tesseract check.

        A missing Tesseract binary is an environment misconfiguration, not a
        per-file problem, so it must fail the whole run up front rather than
        erroring every scanned PDF individually.
        """
        check_tesseract_available()
        return await super().process(starting_path, process_recursively, force, ctx)

    def in_scope(self, entry: Entry) -> bool:
        """Non-PDF entries are never processed, force or not."""
        return entry.media_type == MediaType.pdf

    def should_process(self, session: Session, entry: Entry) -> bool:
        """True only for PDFs with no PdfContents row, or with a stale error."""
        existing_contents = session.get(PdfContents, entry.id)
        existing_error = session.get(Error, (entry.id, self.processing_stage))
        return existing_contents is None or existing_error is not None

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        doc = fitz.open(file_path)
        try:
            if doc.needs_pass:
                # Password-protected -- not a failure, just nothing to extract.
                return

            page_count = doc.page_count
            barcode_match = find_isbn_or_issn_barcode(
                doc, barcode_sample_pages(page_count)
            )
            page_texts = extract_page_texts(doc, text_sample_pages(page_count))
        finally:
            doc.close()

        content = "\n".join(page_texts.values())

        pdf_isbn = barcode_match.isbn if barcode_match else None
        pdf_issn = barcode_match.issn if barcode_match else None
        if pdf_isbn is None and pdf_issn is None:
            pdf_isbn = isbn.extract(content)
        if pdf_isbn is None and pdf_issn is None:
            pdf_issn = issn.extract(content)
        if pdf_isbn is None and pdf_issn is None:
            fallback_extractor = PdfExtractor(file_path)
            pdf_isbn = fallback_extractor.extract_isbn()
            if pdf_isbn is None:
                pdf_issn = fallback_extractor.extract_issn()

        # Persist the non-LLM signal before the fallible LLM step, and commit
        # it now -- if judge_pdf_contents raises below, the base command
        # rolls back the transaction, and an uncommitted merge would be lost
        # right along with the exception, discarding barcode/ISBN/sample-text
        # that had nothing to do with the LLM failure.
        pdf_contents = PdfContents(
            entry_id=entry.id,
            barcode=barcode_match.barcode_text if barcode_match else None,
            isbn=pdf_isbn,
            issn=pdf_issn,
            sample_text=sample_text_json(page_texts),
        )
        session.merge(pdf_contents)
        session.commit()

        if content.strip():
            judgment = judge_pdf_contents(sample_text_json(page_texts))
            pdf_contents.description = judgment.description
            pdf_contents.possible_system = judgment.possible_system
            session.merge(pdf_contents)
