"""Resolve catalog inputs and render bounded visual evidence without judgments."""

from __future__ import annotations

import io
import math
import os
import re
import shutil
import subprocess
import tempfile
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


def _render_postscript(
    path: Path, number: int, max_edge: int, metadata: dict[str, Any]
) -> Image.Image:
    """Render one legacy AI page, inside the existing disposable worker."""
    executable = shutil.which("gs")
    if executable is None:
        raise ValueError(
            "Install Ghostscript (gs) to preview PostScript Illustrator files, "
            "or export a PDF/image from Illustrator."
        )
    if number < 1:
        raise ValueError("Page numbers start at 1.")
    # DSC bounding boxes may be deferred to the trailer. Inspect bounded sections
    # rather than loading an entire (potentially 512 MiB) source into memory.
    with path.open("rb") as stream:
        header = stream.read(64 * 1024)
        stream.seek(max(0, path.stat().st_size - 64 * 1024))
        trailer = stream.read(64 * 1024)
    dimensions = None
    for tag in (b"HiResBoundingBox", b"BoundingBox"):
        for match in re.finditer(
            rb"(?:\A|[\r\n])%%" + tag + rb":([^\r\n]+)", header + b"\n" + trailer
        ):
            try:
                x0, y0, x1, y1 = map(float, match[1].split())
            except ValueError:
                continue
            width, height = x1 - x0, y1 - y0
            if all(math.isfinite(v) and v > 0 for v in (width, height)):
                dimensions = width, height
                break
        if dimensions is not None:
            break
    if dimensions is None:
        raise ValueError(
            "PostScript Illustrator file has no usable bounding box; "
            "export a PDF/image from Illustrator for inspection."
        )
    width, height = dimensions
    scale = min(max_edge / max(width, height), 2.0)
    pixels = [min(max_edge, max(1, math.ceil(value * scale))) for value in dimensions]
    # GS_OPTIONS can inject command flags; this invocation owns its configuration.
    env = {key: value for key, value in os.environ.items() if key != "GS_OPTIONS"}
    with tempfile.TemporaryDirectory(prefix="rpg-ai-preview-") as temporary:
        output = Path(temporary) / "preview.png"
        with (Path(temporary) / "stderr.log").open("w+b") as errors:
            try:
                result = subprocess.run(
                    [
                        executable,
                        "-q",
                        "-dSAFER",
                        "-dBATCH",
                        "-dNOPAUSE",
                        "-dNOEPS",
                        "-dFIXEDMEDIA",
                        "-sDEVICE=png16m",
                        "-dGraphicsAlphaBits=4",
                        "-dTextAlphaBits=4",
                        f"-r{72 * scale}",
                        f"-g{pixels[0]}x{pixels[1]}",
                        f"-dFirstPage={number}",
                        f"-dLastPage={number}",
                        f"-sOutputFile={output}",
                        # Apply the DSC origin on each page, including files with
                        # (atend) bounds that some gs EPSFitPage versions reject.
                        "-c",
                        f"<< /BeginPage {{ pop {-x0} {-y0} translate }} >> "
                        "setpagedevice",
                        "-f",
                        str(path.resolve()),
                        # EPS artwork may omit showpage. LastPage prevents a
                        # duplicate if the source already emitted its first page.
                        *(["-c", "showpage"] if number == 1 else []),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=errors,
                    stderr=errors,
                    env=env,
                    timeout=40,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError(
                    "Ghostscript rendering exceeded 40 seconds."
                ) from error
            if result.returncode:
                errors.seek(0)
                detail = errors.read(1024).decode("utf-8", errors="replace").strip()
                raise ValueError(
                    f"Ghostscript could not render this Illustrator file "
                    f"(exit {result.returncode}): {detail}"
                )
        if not output.exists():
            raise ValueError(f"Ghostscript produced no image for page {number}.")
        with Image.open(output) as original:
            if original.width > max_edge or original.height > max_edge:
                raise ValueError("Ghostscript preview exceeded the dimension limit.")
            image = original.convert("RGB")
    metadata.update(
        page=number,
        page_count=None,  # PostScript does not guarantee a trustworthy page count.
        source_dimensions=list(dimensions),
        source_units="PostScript points",
        render_scale=scale,
        source_format="Adobe Illustrator",
        representation="PostScript artwork",
        renderer="Ghostscript",
    )
    return image


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
    if path.suffix.lower() == ".ai":
        # AI files can have older or generic media classifications in the catalog.
        # Render their artwork without changing that classification.
        media_type = "illustrator"
    if media_type not in {"image", "pdf", "illustrator"}:
        raise UsageError(
            "Visual inspection supports cataloged images, PDFs and "
            "Illustrator (.ai) files with PDF or PostScript artwork."
        )
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
    postscript = False
    if source["media_type"] == "illustrator":
        with path.open("rb") as input_file:
            header = input_file.read(1024)
        postscript = header.startswith(b"%!PS")
        if not postscript and b"%PDF-" not in header:
            raise ValueError(
                "This Illustrator file contains neither readable PDF nor "
                "PostScript artwork. Re-save with Create PDF Compatible File "
                "enabled, or export a PDF/image for inspection."
            )
    if postscript:
        image = _render_postscript(
            path, 1 if page is None else page, max_edge, metadata
        )
    elif source["media_type"] in {"pdf", "illustrator"}:
        number = 1 if page is None else page
        illustrator = source["media_type"] == "illustrator"
        with fitz.open(path, filetype="pdf") as doc:
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
            if illustrator:
                metadata.update(
                    source_format="Adobe Illustrator",
                    representation="PDF-compatible artwork",
                )
    else:
        if page is not None:
            raise ValueError(
                "page applies to PDFs and Illustrator files only; omit it for images."
            )
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
