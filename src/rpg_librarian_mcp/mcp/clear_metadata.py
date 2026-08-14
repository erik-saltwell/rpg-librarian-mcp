"""clear_metadata -- wipe generic and type-specific metadata for reprocessing.

Deletes every row from `FileMetadata` (the generic, embedded-file-properties
table) and every type-specific metadata table (`PdfMetadata`,
`ImageMetadata`, `VideoMetadata`, `AudioMetadata`, `MeshMetadata`). Meant
for the "a metadata extractor had a bug, now every entry needs its
metadata regenerated" situation: with the rows gone,
`UpdateMetadataCommand.should_process` sees a missing `FileMetadata` row
and reprocesses the entry on the next `update_metadata` run, no `force`
flag needed. Does not touch `PdfContents` (identification content from
`read_pdfs`, not extracted metadata) or `Entry`/`Error` rows.
"""

from __future__ import annotations

from fastmcp import FastMCP
from sqlmodel import select

from ..catalog import Catalog
from ..db import session_scope
from ..model import (
    AudioMetadata,
    FileMetadata,
    ImageMetadata,
    MeshMetadata,
    PdfMetadata,
    VideoMetadata,
)
from ..observability import log_event_fields

METADATA_TABLES = {
    "file_metadata": FileMetadata,
    "pdf_metadata": PdfMetadata,
    "image_metadata": ImageMetadata,
    "video_metadata": VideoMetadata,
    "audio_metadata": AudioMetadata,
    "mesh_metadata": MeshMetadata,
}


def clear_metadata(catalog: Catalog) -> dict[str, int]:
    """Delete every generic and type-specific metadata row in the catalog."""
    with session_scope(catalog) as session:
        cleared: dict[str, int] = {}
        for key, model in METADATA_TABLES.items():
            rows = session.exec(select(model)).all()
            for row in rows:
                session.delete(row)
            cleared[key] = len(rows)
        session.commit()

    log_event_fields(**cleared)
    return cleared


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="clear_metadata")
    def clear_metadata_tool() -> dict[str, int]:
        """Delete every generic (`FileMetadata`) and type-specific (pdf/
        image/video/audio/mesh) metadata row in the catalog, so every entry
        is picked up for reprocessing by `update_metadata` on its next run
        -- no `force` needed, since the rows themselves are gone.

        Use this after fixing a bug in a metadata extractor, to wipe out
        metadata it wrote incorrectly across the whole library. Returns the
        number of rows deleted per metadata table.
        """
        return clear_metadata(catalog)
