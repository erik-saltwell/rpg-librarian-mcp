from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import audio, image, mesh, pdf, vector, video
from .base import ExtractionResult

# Keys are identical to schema.MEDIA_METADATA_TABLES -- the single source of
# truth for "which media types have a side table." text/unknown are absent
# from both: no extractor, no side-table row.
EXTRACTORS: dict[str, Callable[[Path], ExtractionResult]] = {
    "pdf": pdf.extract,
    "image": image.extract,
    "vector": vector.extract,
    "audio": audio.extract,
    "mesh": mesh.extract,
    "video": video.extract,
}

__all__ = ["EXTRACTORS", "ExtractionResult"]
