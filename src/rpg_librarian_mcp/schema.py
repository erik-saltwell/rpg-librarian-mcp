from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TableSchema:
    columns: list[str]
    bool_columns: frozenset[str] = field(default_factory=frozenset)
    json_columns: frozenset[str] = field(default_factory=frozenset)


PRODUCTS = TableSchema(
    columns=[
        "id", "folder", "title", "publisher", "author", "url", "description",
        "system", "category", "source", "no_match", "errors",
        "created_at", "updated_at",
    ],
    bool_columns=frozenset({"no_match"}),
    json_columns=frozenset({"errors"}),
)

ENTRIES = TableSchema(
    columns=[
        "id", "filepath", "filename", "extension", "parent_folder", "grandparent_folder",
        "size_in_bytes", "mtime", "sha256", "mime_type", "media_type", "product_id",
        "artist", "title", "publisher", "copyright", "genre", "system", "description",
        "url", "isbn", "issn", "barcode", "source", "llm_no_match",
        "match_source", "match_found", "errors", "created_at", "updated_at",
    ],
    bool_columns=frozenset({"llm_no_match"}),
    json_columns=frozenset({"errors"}),
)

# One side table per media type, holding only that type's fields (`entry_id` is
# the join key back to `entries`, added/stripped by catalog_io rather than
# listed here as ordinary data).
PDF_METADATA = TableSchema(
    columns=["entry_id", "page_count", "is_encrypted", "needs_password", "has_extractable_text", "likely_scanned"],
    bool_columns=frozenset({"is_encrypted", "needs_password", "has_extractable_text", "likely_scanned"}),
)
IMAGE_METADATA = TableSchema(
    columns=["entry_id", "width", "height", "pixel_count", "artists", "copyright", "has_alpha"],
    bool_columns=frozenset({"has_alpha"}),
)
SVG_METADATA = TableSchema(columns=["entry_id", "width", "height", "units", "view_box"])
AUDIO_METADATA = TableSchema(columns=["entry_id", "duration"])
MESH_METADATA = TableSchema(
    columns=["entry_id", "bounding_box_x_mm", "bounding_box_y_mm", "bounding_box_z_mm", "surface_area_cm2", "unit"]
)
VIDEO_METADATA = TableSchema(
    columns=["entry_id", "duration_seconds", "width", "height", "has_audio", "title", "artist", "comment"],
    bool_columns=frozenset({"has_audio"}),
)

# entries.media_type -> (side table name, its schema). text/unknown have no
# side table -- media_type_metadata is None for those, matching the pydantic
# MediaTypeMetadata union in the original rpg-librarian project.
MEDIA_METADATA_TABLES: dict[str, tuple[str, TableSchema]] = {
    "pdf": ("pdf_metadata", PDF_METADATA),
    "image": ("image_metadata", IMAGE_METADATA),
    "vector": ("svg_metadata", SVG_METADATA),
    "audio": ("audio_metadata", AUDIO_METADATA),
    "mesh": ("mesh_metadata", MESH_METADATA),
    "video": ("video_metadata", VIDEO_METADATA),
}
