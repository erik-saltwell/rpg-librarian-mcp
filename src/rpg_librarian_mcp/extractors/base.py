from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractionResult:
    """Output of one media-type extractor: the type-specific side-table
    fields (matching the corresponding entry in schema.MEDIA_METADATA_TABLES,
    minus entry_id) plus whatever universal identity fields (entries.artist/
    title/publisher/copyright/genre/description/... -- the "base metadata")
    the format's embedded tags contributed."""

    media_type_metadata: dict[str, Any] = field(default_factory=dict)
    base_metadata: dict[str, Any] = field(default_factory=dict)
