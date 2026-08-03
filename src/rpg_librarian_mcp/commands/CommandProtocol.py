from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Protocol, TypeVar

from ..progress import ProgressReporter

ResultType = TypeVar("ResultType", covariant=True, bound=NamedTuple)


class CommandProtocol(Protocol[ResultType]):
    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        reporter: ProgressReporter,
    ) -> ResultType: ...
