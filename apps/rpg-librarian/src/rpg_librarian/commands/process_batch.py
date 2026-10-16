"""Single-invocation unattended inbox processing."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..batch.runner import run_batch


def run(args: argparse.Namespace, catalog_path: Path) -> int:
    return run_batch(catalog_path.resolve(), args.root.expanduser().resolve())
