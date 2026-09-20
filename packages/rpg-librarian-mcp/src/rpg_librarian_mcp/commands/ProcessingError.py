from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


class ProcessingError(NamedTuple):
    path: Path
    reason: str
