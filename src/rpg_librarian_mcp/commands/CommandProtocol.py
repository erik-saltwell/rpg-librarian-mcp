from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Protocol, TypeVar

from fastmcp import Context

ResultType = TypeVar("ResultType", covariant=True, bound=NamedTuple)


class CommandProtocol(Protocol[ResultType]):
    async def process(
        self,
        starting_path: Path,
        process_recursively: bool,
        force: bool,
        ctx: Context,
    ) -> ResultType: ...
