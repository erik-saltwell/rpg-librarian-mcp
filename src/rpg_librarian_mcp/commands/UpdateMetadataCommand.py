from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from rpg_librarian_mcp.catalog import Catalog

from ..metadata.extractors import generate_extractor
from ..model import Entry, Error, FileMetadata, ProcessingStage
from .UpdateBaseCommand import UpdateBaseCommand


class UpdateMetadataCommand(UpdateBaseCommand):
    def __init__(
        self,
        catalog: Catalog,
        processing_stage: ProcessingStage,
        max_errors: int = 50,
    ) -> None:
        super().__init__(catalog, processing_stage, max_errors)

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
        extractor = generate_extractor(entry.media_type, file_path)

        file_metadata = extractor.extract_file_metadata()
        file_metadata.entry_id = entry.id
        session.merge(file_metadata)

        custom_metadata = extractor.extract_custom_metadata()
        if custom_metadata is not None:
            custom_metadata.entry_id = entry.id
            session.merge(custom_metadata)
