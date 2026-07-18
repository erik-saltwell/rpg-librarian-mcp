from __future__ import annotations

import mimetypes
from pathlib import Path

import magic

# Extension-first overrides: libmagic often can't tell these apart from a
# generic zip/xml/octet-stream, or gets them wrong, so a known extension wins
# before we ever sniff file content.
_SVG_EXTENSIONS = {".svg", ".svgz"}

_MESH_EXTENSION_MIME: dict[str, str] = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".obj": "model/obj",
    ".stl": "model/stl",
    ".fbx": "model/x-fbx",
    ".dae": "model/vnd.collada+xml",
    ".blend": "model/x-blender",
    ".3ds": "model/x-3ds",
    ".ply": "model/x-ply",
    ".lys": "model/x-lys",
    ".3mf": "model/3mf",
}

_DOC_EBOOK_EXTENSION_MIME: dict[str, str] = {
    ".rtf": "application/rtf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".mobi": "application/x-mobipocket-ebook",
    ".epub": "application/epub+zip",
}

_SNIFF_BYTES = 8192
_NO_ANSWER_MIME = "application/octet-stream"


def find_mime_type(path: Path) -> str | None:
    """Best-effort MIME type for `path`: known-extension overrides first
    (libmagic is unreliable for these), then content sniffing via libmagic,
    then the stdlib mimetypes guess as a last resort."""
    extension = path.suffix.lower()

    if extension in _SVG_EXTENSIONS:
        return "image/svg+xml"
    if extension in _MESH_EXTENSION_MIME:
        return _MESH_EXTENSION_MIME[extension]
    if extension in _DOC_EBOOK_EXTENSION_MIME:
        return _DOC_EBOOK_EXTENSION_MIME[extension]

    try:
        with path.open("rb") as handle:
            sniffed = magic.from_buffer(handle.read(_SNIFF_BYTES), mime=True)
    except Exception:
        sniffed = None
    if sniffed and sniffed != _NO_ANSWER_MIME:
        return sniffed

    guessed, _ = mimetypes.guess_type(str(path))
    return guessed


def media_type_for_mime(mime_type: str | None, extension: str) -> str:
    """Map a MIME type (as returned by find_mime_type) to one of the
    entries.media_type enum values: audio, video, image, vector, pdf, mesh,
    text, unknown."""
    if mime_type is None:
        return "unknown"
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type == "image/svg+xml":
        return "vector"
    if mime_type in _DOC_EBOOK_EXTENSION_MIME.values():
        return "text"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("model/"):
        return "mesh"
    if mime_type.startswith("text/"):
        return "text"
    return "unknown"
