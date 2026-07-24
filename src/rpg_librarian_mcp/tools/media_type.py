from __future__ import annotations

import mimetypes
from pathlib import Path

import magic

from ..model.MediaType import MediaType

GENERIC_MIME_TYPE: str = "application/octet-stream"
GENERIC_MEDIA_TYPE: MediaType = MediaType.unknown

# Mime types that carry no useful classification signal on their own (a bare
# binary blob, or a generic zip container shared by many unrelated formats
# such as .3mf, .docx, .epub, .jar, ...). When magic reports one of these we
# fall back to the file extension instead.
GENERIC_MIME_TYPES: frozenset[str] = frozenset(
    {
        GENERIC_MIME_TYPE,
        "application/zip",
    }
)

KNOWN_EXTENSIONS: dict[str, MediaType] = {
    # audio
    "wav": MediaType.audio,
    "mp3": MediaType.audio,
    "ogg": MediaType.audio,
    "m4a": MediaType.audio,
    "flac": MediaType.audio,
    # video
    "mp4": MediaType.video,
    "m4v": MediaType.video,
    "webm": MediaType.video,
    "mpg": MediaType.video,
    "mpeg": MediaType.video,
    # image
    "png": MediaType.image,
    "jpg": MediaType.image,
    "jpeg": MediaType.image,
    "webp": MediaType.image,
    "gif": MediaType.image,
    "bmp": MediaType.image,
    "tif": MediaType.image,
    "tiff": MediaType.image,
    "psd": MediaType.image,
    # vector
    "svg": MediaType.vector,
    "ai": MediaType.vector,
    "vsd": MediaType.vector,
    "vsdx": MediaType.vector,
    # pdf
    "pdf": MediaType.pdf,
    # mesh (3D models / printables)
    "stl": MediaType.mesh,
    "3mf": MediaType.mesh,
    "obj": MediaType.mesh,
    "lys": MediaType.mesh,
    # text / documents
    "txt": MediaType.text,
    "md": MediaType.text,
    "html": MediaType.text,
    "xml": MediaType.text,
    "json": MediaType.text,
    "jsonl": MediaType.text,
    "yml": MediaType.text,
    "yaml": MediaType.text,
    "csv": MediaType.text,
    "doc": MediaType.text,
    "docx": MediaType.text,
    "rtf": MediaType.text,
    "odt": MediaType.text,
    "epub": MediaType.text,
    "mobi": MediaType.text,
    "azw3": MediaType.text,
    "tex": MediaType.text,
    "opf": MediaType.text,
    "py": MediaType.text,
    "js": MediaType.text,
    "lst": MediaType.text,
    "asc": MediaType.text,
    "dot": MediaType.text,
    "por": MediaType.text,
    "smp": MediaType.text,
    "gitignore": MediaType.text,
    "dd": MediaType.text,
    "gcode": MediaType.text,
    "scad": MediaType.text,
}

KNOWN_MIME_TYPES: dict[str, MediaType] = {
    # audio
    "audio/x-wav": MediaType.audio,
    "audio/wav": MediaType.audio,
    "audio/mpeg": MediaType.audio,
    "audio/x-m4a": MediaType.audio,
    "audio/mp4": MediaType.audio,
    "audio/flac": MediaType.audio,
    "audio/ogg": MediaType.audio,
    # video
    "video/mp4": MediaType.video,
    "video/x-m4v": MediaType.video,
    "video/webm": MediaType.video,
    "video/mpeg": MediaType.video,
    # image
    "image/png": MediaType.image,
    "image/jpeg": MediaType.image,
    "image/webp": MediaType.image,
    "image/gif": MediaType.image,
    "image/bmp": MediaType.image,
    "image/tiff": MediaType.image,
    "image/vnd.adobe.photoshop": MediaType.image,
    # vector
    "image/svg+xml": MediaType.vector,
    "application/vnd.ms-visio.drawing.main+xml": MediaType.vector,
    # pdf (also covers .ai files, which are PDF-compatible under the hood)
    "application/pdf": MediaType.pdf,
    # text / documents
    "text/plain": MediaType.text,
    "text/html": MediaType.text,
    "text/x-script.python": MediaType.text,
    "application/javascript": MediaType.text,
    "text/xml": MediaType.text,
    "application/xml": MediaType.text,
    "text/csv": MediaType.text,
    "text/rtf": MediaType.text,
    "application/rtf": MediaType.text,
    "application/json": MediaType.text,
    "application/x-ndjson": MediaType.text,
    "application/postscript": MediaType.text,
    "text/x-tex": MediaType.text,
    "application/epub+zip": MediaType.text,
    "application/x-mobipocket-ebook": MediaType.text,
    "application/msword": MediaType.text,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        MediaType.text
    ),
    "application/vnd.oasis.opendocument.text": MediaType.text,
}


def _detect_mime_type_using_contents(path: Path) -> str | None:
    """Detect MIME type from file contents using libmagic."""
    try:
        return magic.from_file(str(path), mime=True)
    except Exception:
        return None


def _detect_mime_from_extension(path: Path) -> str | None:
    """Guess MIME type from filename extension only."""
    mime_type, _encoding = mimetypes.guess_type(path.name)
    return mime_type


def detect_mime_type(path: Path) -> str:
    mime_type: str | None = _detect_mime_type_using_contents(path)
    if not mime_type:
        mime_type = _detect_mime_from_extension(path)
    if not mime_type:
        return GENERIC_MIME_TYPE
    else:
        return mime_type


def _detect_media_type_by_extension(extension: str) -> MediaType:
    normalized = extension.lower().removeprefix(".")
    if normalized in KNOWN_EXTENSIONS:
        return KNOWN_EXTENSIONS[normalized]
    return GENERIC_MEDIA_TYPE


def _detect_media_type_by_mime_type(mime_type: str) -> MediaType:
    if mime_type in KNOWN_MIME_TYPES:
        return KNOWN_MIME_TYPES[mime_type]
    return GENERIC_MEDIA_TYPE


def detect_media_type(mime_type: str, extension: str) -> MediaType:
    if mime_type in GENERIC_MIME_TYPES:
        return _detect_media_type_by_extension(extension)
    return _detect_media_type_by_mime_type(mime_type)
