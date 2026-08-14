from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from rpg_librarian_mcp.catalog import Catalog

from ..metadata.extractors import generate_extractor
from ..model import Entry, Error, FileMetadata, ProcessingStage
from ..progress import ProgressReporter
from ..tools.isolated_worker import IsolatedWorkerPool, WorkerPool
from ..tools.ocr import check_tesseract_available
from .UpdateBaseCommand import UpdateBaseCommand, UpdateResult


class UpdateMetadataCommand(UpdateBaseCommand):
    def __init__(
        self,
        catalog: Catalog,
        processing_stage: ProcessingStage,
        max_errors: int = 50,
        mesh_pool: WorkerPool | None = None,
    ) -> None:
        super().__init__(catalog, processing_stage, max_errors)
        # Persists across the whole command's lifetime (the MCP server's,
        # in practice -- commands are constructed once at startup) rather
        # than per file, so the worker subprocess stays up between files
        # instead of paying a spawn per mesh. See `IsolatedWorkerPool`.
        self._mesh_pool: WorkerPool = (
            mesh_pool if mesh_pool is not None else IsolatedWorkerPool()
        )

    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        reporter: ProgressReporter,
    ) -> UpdateResult:
        """Same as the base `process`, plus a one-time Tesseract check.

        `PdfExtractor` now OCRs single-page PDFs to detect image-only
        content (see `is_likely_image_only`), so a missing Tesseract binary
        is an environment misconfiguration for this command too -- same
        reasoning as `ReadPdfsCommand`: fail the whole run up front rather
        than erroring every single-page PDF individually.
        """
        check_tesseract_available()
        return await super().process(
            starting_path, process_recursively, force, reporter
        )

    def should_process(self, session: Session, entry: Entry) -> bool:
        """False if a FileMetadata row exists for this entry and it has no errors."""
        existing_file_metadata = session.get(FileMetadata, entry.id)
        existing_error = session.get(Error, (entry.id, self.processing_stage))
        return existing_file_metadata is None or existing_error is not None

    def process_one(self, session: Session, file_path: Path, entry: Entry) -> None:
        """Get the media type, and use it to get a metadata extractor,
        then it should generate file metadata and type specific metadata.
        Finally, it should upsert all this data into the database.
        """
        extractor = generate_extractor(entry.media_type, file_path, self._mesh_pool)

        file_metadata = extractor.extract_file_metadata()
        file_metadata.entry_id = entry.id
        session.merge(file_metadata)

        custom_metadata = extractor.extract_custom_metadata()
        if custom_metadata is not None:
            custom_metadata.entry_id = entry.id
            session.merge(custom_metadata)
