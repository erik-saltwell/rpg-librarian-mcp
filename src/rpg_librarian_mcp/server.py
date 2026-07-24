"""FastMCP server wiring: build the server, register every tool module."""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from .config import Config, load_env
from .mcp import REGISTRARS

log = logging.getLogger(__name__)


def configure_logging() -> None:
    """Log to stderr only -- stdout is the stdio transport's message channel."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_server() -> FastMCP:
    """Build the server with all tools registered."""
    env_path = load_env()
    config = Config.from_cwd()

    mcp = FastMCP(name="rpg-librarian-mcp")
    for register in REGISTRARS:
        register(mcp, config)

    log.info("env loaded from %s", env_path or "<none>")
    log.info("library root %s (catalog %s)", config.library_root, config.catalog_dir)
    return mcp


def run() -> None:
    configure_logging()
    create_server().run(transport="stdio")
