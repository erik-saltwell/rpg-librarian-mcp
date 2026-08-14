"""read_pdfs -- extract barcode/ISBN/ISSN/sample-text/LLM-derived signal from PDFs."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.ReadPdfsCommand import ReadPdfsCommand
from ..model import ProcessingStage
from ..progress import McpProgressReporter


def register(mcp: FastMCP, catalog: Catalog) -> None:
    command = ReadPdfsCommand(catalog, ProcessingStage.read_pdfs)

    @mcp.tool
    async def read_pdfs(
        path: Path,
        ctx: Context,
        process_recursively: bool = False,
        force: bool = False,
        ignore_likely_image_only: bool = False,
    ) -> dict[str, object]:
        """Extract and persist barcode/ISBN/ISSN/sample-text/LLM-derived
        signal for a PDF file or directory of PDFs.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set. Non-PDF entries are skipped, not
        errored. `force` bypasses the "skip if unchanged" check and
        reprocesses every matched PDF. `ignore_likely_image_only` skips PDFs
        that look like a single-page image with no real text (e.g. a
        poster/battle map) instead of reading them -- those are typically
        slow to OCR and yield little or no useful text.
        """
        result = await command.process(
            path,
            process_recursively,
            force,
            McpProgressReporter(ctx),
            ignore_likely_image_only=ignore_likely_image_only,
        )
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
