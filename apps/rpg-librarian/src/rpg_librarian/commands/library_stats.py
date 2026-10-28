"""CLI adapter: rebuild the markdown stats report beside the catalog."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..services.library_stats import write_report


def run(args: argparse.Namespace, catalog: Path) -> int:
    print(write_report(catalog.resolve()))
    return 0
