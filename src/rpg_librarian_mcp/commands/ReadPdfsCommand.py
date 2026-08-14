from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import fitz
import litellm
from sqlmodel import Session

from ..catalog import Catalog
from ..isbn import isbn, issn
from ..llm.pdf_judgment import judge_pdf_contents
from ..metadata.extractors.pdf_extractor import PdfExtractor
from ..model import Entry, Error, MediaType, PdfContents, PdfMetadata, ProcessingStage
from ..observability import log_entry_fields
from ..progress import ProgressReporter
from ..tools.barcode import find_isbn_or_issn_barcode_isolated
from ..tools.isolated_worker import IsolatedWorkerPool, WorkerPool
from ..tools.ocr import check_tesseract_available
from ..tools.text_extraction import (
    barcode_sample_pages,
    extract_page_texts_isolated,
    sample_text_json,
    text_sample_pages,
)
from .UpdateBaseCommand import UpdateBaseCommand, UpdateResult


class ReadPdfsCommand(UpdateBaseCommand):
    fatal_exceptions: ClassVar[tuple[type[BaseException], ...]] = (
        litellm.AuthenticationError,
        litellm.RateLimitError,
    )

    def __init__(
        self,
        catalog: Catalog,
        processing_stage: ProcessingStage,
        max_errors: int = 50,
        pdf_pool: WorkerPool | None = None,
    ) -> None:
        super().__init__(catalog, processing_stage, max_errors)
        # Same reasoning as `UpdateMetadataCommand._mesh_pool` -- one
        # worker subprocess, persisting for the command's whole lifetime.
        self._pdf_pool: WorkerPool = (
            pdf_pool if pdf_pool is not None else IsolatedWorkerPool()
        )
        self._ignore_likely_image_only = False

    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        reporter: ProgressReporter,
        ignore_likely_image_only: bool = False,
    ) -> UpdateResult:
        """Same as the base `process`, plus a one-time Tesseract check.

        A missing Tesseract binary is an environment misconfiguration, not a
        per-file problem, so it must fail the whole run up front rather than
        erroring every scanned PDF individually.

        `ignore_likely_image_only` is stashed on `self` for `process_one` to
        read -- `process_one`'s signature is fixed by `UpdateBaseCommand`, so
        it can't take this as a direct argument.
        """
        self._ignore_likely_image_only = ignore_likely_image_only
        check_tesseract_available()
        return await super().process(
            starting_path, process_recursively, force, reporter
        )

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
        finally:
            doc.close()

        # `UpdateMetadataCommand` (stage `extract_metadata`, which always
        # runs before `read_pdfs`) already computed and persisted this via
        # `PdfExtractor` -- no need to redo the render+OCR work here. A
        # missing/undetermined row is treated as not image-only, same as
        # `PdfExtractor._get_likely_image_only`'s `None` case.
        pdf_metadata = session.get(PdfMetadata, entry.id)
        likely_image_only = bool(pdf_metadata and pdf_metadata.likely_image_only)

        if likely_image_only:
            self._process_likely_image_only(session, file_path, entry, page_count)
        else:
            self._process_normal(session, file_path, entry, page_count)

    def _process_likely_image_only(
        self, session: Session, file_path: Path, entry: Entry, page_count: int
    ) -> None:
        if self._ignore_likely_image_only:
            return
        self._process_normal(session, file_path, entry, page_count)

    def _process_normal(
        self, session: Session, file_path: Path, entry: Entry, page_count: int
    ) -> None:
        # Both isolated in the same worker subprocess/timeout -- PyMuPDF
        # rendering is the risky part of this file, whether it's rendering
        # for barcode scanning or for OCR, and either can hang or crash on
        # a malformed page. Each reopens `file_path` itself; see
        # `find_isbn_or_issn_barcode_isolated` / `extract_page_texts_isolated`.
        barcode_match = self._pdf_pool.submit(
            find_isbn_or_issn_barcode_isolated,
            file_path,
            barcode_sample_pages(page_count),
        )

        page_text_result = self._pdf_pool.submit(
            extract_page_texts_isolated, file_path, text_sample_pages(page_count)
        )
        page_texts = page_text_result.page_texts

        log_entry_fields(
            page_count=page_count,
            barcode_matched=barcode_match is not None,
            pages_sampled=page_text_result.pages_sampled,
            pages_direct_extraction=page_text_result.pages_direct_extraction,
            pages_ocr=page_text_result.pages_ocr,
        )

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

        llm_judged = bool(content.strip())
        log_entry_fields(llm_judged=llm_judged)
        if llm_judged:
            judgment = judge_pdf_contents(sample_text_json(page_texts))
            pdf_contents.description = judgment.description
            pdf_contents.possible_system = judgment.possible_system
            session.merge(pdf_contents)
