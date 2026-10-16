"""Resolve catalog inputs and render bounded visual evidence without judgments."""

from __future__ import annotations

import io
import math
import warnings
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageOps
from sqlmodel import Session, col, select

from ..errors import UsageError
from ..model import Entry, File, Root

_MAX_INPUT_BYTES = 512 * 1024**2
_MAX_IMAGE_PIXELS = 40_000_000
_MAX_OUTPUT_BYTES = 8 * 1024**2


def resolve_visual(
    session: Session,
    entry_id: int,
    member_path: str | None,
    root_id: int | None,
) -> dict[str, Any]:
    entry = session.get(Entry, entry_id)
    if entry is None:
        raise UsageError("Entry no longer exists; refresh the worklist.")
    if entry.file_id is not None:
        if member_path is not None or root_id is not None:
            raise UsageError(
                "For a loose file, pass only entry_id (no member selectors)."
            )
        file = session.get(File, entry.file_id)
    else:
        if not member_path:
            raise UsageError(
                "For a pack, select member_path using relative_path from report-pack; "
                "include root_id if ambiguous."
            )
        query = select(File).where(
            col(File.pack_id) == entry.pack_id,
            col(File.relative_path) == member_path,
        )
        if root_id is not None:
            query = query.where(col(File.root_id) == root_id)
        matches = session.exec(query).all()
        if len(matches) != 1:
            raise UsageError(
                "Member not found or ambiguous; use relative_path and root_id "
                "from report-pack for this pack."
            )
        file = matches[0]
    if file is None or file.missing_since is not None:
        raise UsageError("This file is missing; refresh the catalog.")
    root = session.get(Root, file.root_id)
    if root is None:
        raise UsageError("The file's registered root no longer exists.")
    base = Path(root.path).resolve()
    path = (base / file.relative_path).resolve()
    if not path.is_relative_to(base):
        raise UsageError("The catalog path escapes its registered root.")
    media_type = file.media_type.value if file.media_type else None
    if media_type not in {"image", "pdf"}:
        raise UsageError("Visual inspection supports cataloged images and PDFs only.")
    return {
        "entry_id": entry_id,
        "root_id": file.root_id,
        "relative_path": file.relative_path,
        "path": str(path),
        "media_type": media_type,
    }


def render_visual(
    source: dict[str, Any], page: int | None, max_edge: int
) -> tuple[dict[str, Any], bytes]:
    """Worker entry point; decoding/rendering never runs in the MCP process."""
    if not 512 <= max_edge <= 2400:
        raise ValueError("max_edge must be between 512 and 2400 pixels.")
    path = Path(source["path"])
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the 512 MiB visual inspection limit.")
    metadata = dict(source)
    if source["media_type"] == "pdf":
        number = 1 if page is None else page
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("PDF is password protected.")
            if not 1 <= number <= doc.page_count:
                raise ValueError(f"Page must be between 1 and {doc.page_count}.")
            pdf_page = doc[number - 1]
            width, height = pdf_page.rect.width, pdf_page.rect.height
            if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                raise ValueError("PDF page has invalid dimensions.")
            scale = min(max_edge / max(width, height), 2.0)
            pix = pdf_page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False
            )
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            metadata.update(
                page=number,
                page_count=doc.page_count,
                source_dimensions=[width, height],
                source_units="PDF points",
                render_scale=scale,
            )
    else:
        if page is not None:
            raise ValueError("page applies to PDFs only; omit it for images.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as original:
                if original.width * original.height > _MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds the 40 megapixel decoding limit.")
                metadata.update(
                    source_dimensions=list(original.size),
                    source_units="pixels",
                    frame=1,
                )
                image = ImageOps.exif_transpose(original)
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                rgba = image.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
    try:
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        data = output.getvalue()
        if len(data) > _MAX_OUTPUT_BYTES:
            raise ValueError("Rendered image exceeds the 8 MiB output limit.")
        metadata.update(
            rendered_dimensions=list(image.size),
            max_edge=max_edge,
            mime_type="image/jpeg",
            preview="Bounded JPEG preview; images may be resized.",
        )
        return metadata, data
    finally:
        image.close()
