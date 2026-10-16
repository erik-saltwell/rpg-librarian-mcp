"""Cooperative lock for catalog-wide orchestration, not individual MCP writes."""

from __future__ import annotations

import fcntl
import hashlib
from contextlib import contextmanager
from pathlib import Path

from ..errors import UsageError


@contextmanager
def catalog_job_lock(catalog: Path):
    identity = hashlib.sha256(str(catalog.resolve()).encode()).hexdigest()[:16]
    directory = catalog.parent / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"orchestration-{identity}.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UsageError(
                "Another batch, source sync or import is running for this catalog."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
