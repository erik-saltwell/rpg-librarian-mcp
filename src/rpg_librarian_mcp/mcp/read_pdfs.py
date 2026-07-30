"""read_pdfs -- extract barcode/ISBN/ISSN/sample-text/LLM-derived signal from PDFs."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP

from ..catalog import Catalog
from ..commands.ReadPdfsCommand import ReadPdfsCommand
from ..model import ProcessingStage


def register(mcp: FastMCP, catalog: Catalog) -> None:
    command = ReadPdfsCommand(catalog, ProcessingStage.read_pdfs)

    @mcp.tool
    async def read_pdfs(
        path: Path,
        ctx: Context,
        process_recursively: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        """Extract and persist barcode/ISBN/ISSN/sample-text/LLM-derived
        signal for a PDF file or directory of PDFs.

        `path` must be an absolute path, and may be a single file or a
        directory; directories are non-recursive unless
        `process_recursively` is set. Non-PDF entries are skipped, not
        errored. `force` bypasses the "skip if unchanged" check and
        reprocesses every matched PDF.
        """
        result = await command.process(path, process_recursively, force, ctx)
        return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}
