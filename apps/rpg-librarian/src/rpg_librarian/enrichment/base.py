from __future__ import annotations

import os
from collections.abc import Callable
from typing import Protocol

from ..model import ProcessingStage
from ..model.core import EntryMetadataBase, FileMetadataBase
from .queries import FileContext


class FatalSourceError(Exception):
    """A source is unusable for the rest of the run (bad key, exhausted quota).

    Retrying the next file would fail identically, so the source stops instead of
    recording an error against every remaining file.
    """


class Source(Protocol):
    """One kind of evidence `enrich` can gather for a file."""

    @property
    def name(self) -> str:
        """The `--source` value."""
        ...

    @property
    def stage(self) -> ProcessingStage:
        """The stage an `error` row for this source is recorded under."""
        ...

    @property
    def table(self) -> type[EntryMetadataBase | FileMetadataBase]:
        """The table holding this source's rows: one per entry, or (ISBN) per file."""
        ...

    def unavailable_reason(self) -> str | None:
        """Why this source cannot run (a missing credential), else None."""
        ...

    def begin_run(self) -> None:
        """Reset anything a source remembers from an earlier run."""
        ...

    def wants(self, context: FileContext) -> bool:
        """Whether this file is worth a request for this source."""
        ...

    def fetch(
        self, context: FileContext
    ) -> EntryMetadataBase | FileMetadataBase | None:
        """Look the file up. The caller sets the returned row's key."""
        ...


def require_env(variable: str) -> Callable[[], str | None]:
    def check() -> str | None:
        return None if os.environ.get(variable) else f"{variable} is not set"

    return check
