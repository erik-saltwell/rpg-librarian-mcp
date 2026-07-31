from __future__ import annotations

from pathlib import Path
from typing import Any

from ...model import MediaType
from ..MetadataExtractor import MetadataExtractor
from .audio_extractor import AudioExtractor
from .image_extractor import ImageExtractor
from .mesh_extractor import MeshExtractor
from .pdf_extractor import PdfExtractor
from .svg_extractor import SvgExtractor
from .video_extractor import VideoExtractor

# trimesh-loadable mesh formats. .lys (Lychee Slicer project) is also
# classified as MediaType.mesh -- it's a real 3D-print project file and
# catalogable as such -- but trimesh doesn't understand its internal layout
# and raises NotImplementedError, so it's routed to NoMetadataExtractor
# instead of MeshExtractor.
_SUPPORTED_MESH_EXTENSIONS = {"stl", "3mf", "obj"}


class NoMetadataExtractor(MetadataExtractor):
    def extract_value(self, field: str) -> str | None:
        return None

    def extract_custom_metadata(self) -> Any | None:
        return None


def generate_extractor(media_type: MediaType, file_path: Path) -> MetadataExtractor:
    match media_type:
        case MediaType.audio:
            return AudioExtractor(file_path)
        case MediaType.image:
            if file_path.name.lower().endswith(".svg"):
                return SvgExtractor(file_path)
            else:
                return ImageExtractor(file_path)
        case MediaType.mesh:
            extension = file_path.suffix.lower().removeprefix(".")
            if extension not in _SUPPORTED_MESH_EXTENSIONS:
                return NoMetadataExtractor()
            return MeshExtractor(file_path)
        case MediaType.video:
            return VideoExtractor(file_path)
        case MediaType.pdf:
            return PdfExtractor(file_path)
        case _:
            return NoMetadataExtractor()
