from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class MediaType(StrEnum):
    audio = "audio"
    video = "video"
    image = "image"
    vector = "vector"
    pdf = "pdf"
    mesh = "mesh"
    text = "text"
    unknown = "unknown"


from ._file_hash import generate_file_size, generate_sha256  # noqa: E402
from ._media_type import detect_media_type, detect_mime_type  # noqa: E402


@dataclass(frozen=True, slots=True)
class FileInspection:
    size_in_bytes: int
    sha256: str
    mime_type: str
    media_type: MediaType


def inspect_file(path: Path) -> FileInspection:
    """Collect the stable cataloging signals for one explicit file."""
    mime_type = detect_mime_type(path)
    return FileInspection(
        size_in_bytes=generate_file_size(path),
        sha256=generate_sha256(path),
        mime_type=mime_type,
        media_type=detect_media_type(mime_type, path.suffix),
    )
