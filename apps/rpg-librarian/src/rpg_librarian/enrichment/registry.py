from __future__ import annotations

from .base import Source
from .dtrpg import DtrpgSource
from .google import GoogleSource
from .isbn import IsbnSource
from .rpggeek import RpggeekSource
from .text_analysis import TextAnalysisSource

# Run order: cheap identifiers first, the LLM last.
SOURCES: dict[str, Source] = {
    source.name: source
    for source in (
        IsbnSource(),
        DtrpgSource(),
        RpggeekSource(),
        GoogleSource(),
        TextAnalysisSource(),
    )
}
