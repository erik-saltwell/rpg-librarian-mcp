from __future__ import annotations

import argparse
from pathlib import Path

from ..server import run as run_server


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    """Serve the MCP tools on stdio until the client disconnects."""
    run_server(catalog_path)
    return 0
