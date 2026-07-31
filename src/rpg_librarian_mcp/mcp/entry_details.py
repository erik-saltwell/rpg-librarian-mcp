"""get_entry_details -- one entry plus every row in every table linked to it."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from sqlmodel import select

from ..catalog import Catalog
from ..db import session_scope
from ..model import (
    AudioMetadata,
    Error,
    FileMetadata,
    ImageMetadata,
    MeshMetadata,
    PdfContents,
    PdfMetadata,
    Product,
    ReviewFlag,
    VideoMetadata,
)
from ..tools.entry_queries import entry_by_exact_path

# entry_id-keyed tables (one row per entry, or none) -- every model built on
# EntryMetadataBase (model/core.py). Adding a new one here is the only step
# needed for get_entry_details to pick it up.
_METADATA_TABLES = {
    "file_metadata": FileMetadata,
    "pdf_metadata": PdfMetadata,
    "pdf_contents": PdfContents,
    "image_metadata": ImageMetadata,
    "audio_metadata": AudioMetadata,
    "video_metadata": VideoMetadata,
    "mesh_metadata": MeshMetadata,
}


def get_entry_details(catalog: Catalog, path: Path) -> dict[str, object]:
    """One entry's own row plus every related row across the schema:
    its Product (if linked), all Error rows, all ReviewFlag rows (open and
    resolved), and whichever type-specific metadata tables have a row."""
    relative_path = catalog.to_relative(path)

    with session_scope(catalog) as session:
        entry = entry_by_exact_path(session, relative_path.parent, relative_path.name)
        if entry is None:
            raise ValueError(f"{path} is not cataloged -- run update_catalog first")

        product = session.get(Product, entry.product_id) if entry.product_id else None
        errors = session.exec(select(Error).where(Error.entry_id == entry.id)).all()
        review_flags = session.exec(
            select(ReviewFlag).where(ReviewFlag.entry_id == entry.id)
        ).all()

        metadata = {}
        for name, model in _METADATA_TABLES.items():
            row = session.get(model, entry.id)
            if row is not None:
                metadata[name] = row.model_dump(mode="json")

        return {
            "path": str(entry.path),
            "entry": entry.model_dump(mode="json"),
            "product": product.model_dump(mode="json") if product else None,
            # Error.stage is stored via a raw Column override (see
            # model/Error.py), so model_dump doesn't recognize it as the
            # ProcessingStage enum it's typed as -- serialize explicitly,
            # matching list_errors.py's own shape, instead of a warning-prone
            # generic model_dump.
            "errors": [
                {
                    "stage": error.stage,
                    "error_text": error.error_text,
                    "occurred_at": error.occurred_at.isoformat(),
                }
                for error in errors
            ],
            "review_flags": [flag.model_dump(mode="json") for flag in review_flags],
            "metadata": metadata,
        }


def register(mcp: FastMCP, catalog: Catalog) -> None:
    @mcp.tool(name="get_entry_details")
    def get_entry_details_tool(path: Path) -> dict[str, object]:
        """One entry's own row plus every related row across the schema:
        its Product (if linked), all Error rows, all ReviewFlag rows (open
        and resolved), and whichever type-specific metadata tables have a
        row (file_metadata, pdf_metadata, pdf_contents, image_metadata,
        audio_metadata, video_metadata, mesh_metadata).

        `path` must be an absolute path to a single cataloged file.
        """
        return get_entry_details(catalog, path)
