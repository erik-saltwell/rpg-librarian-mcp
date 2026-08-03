"""FastMCP server wiring: build the server, register every tool module."""

from __future__ import annotations

import logging
import sys

import structlog
from fastmcp import FastMCP

from .catalog import Catalog, load_env
from .mcp import REGISTRARS
from .observability import ToolCallLoggingMiddleware, configure_wide_event_logs

log = logging.getLogger(__name__)


def configure_logging() -> None:
    """Log to stderr only -- stdout is the stdio transport's message channel."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


# structlog's unconfigured default renders to stdout, which would corrupt the
# stdio transport -- configure it at import time so every path to
# `create_server()` (tests included, not just `run()`) gets stderr JSON.
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=True,
)


def create_server() -> FastMCP:
    """Build the server with all tools registered."""
    env_path = load_env()
    config = Catalog.from_cwd()
    configure_wide_event_logs(config.catalog_dir)

    mcp = FastMCP(name="rpg-librarian-mcp")
    mcp.add_middleware(ToolCallLoggingMiddleware())
    for register in REGISTRARS:
        register(mcp, config)

    log.info("env loaded from %s", env_path or "<none>")
    log.info("library root %s (catalog %s)", config.library_root, config.catalog_dir)
    return mcp


def run() -> None:
    configure_logging()
    create_server().run(transport="stdio")
