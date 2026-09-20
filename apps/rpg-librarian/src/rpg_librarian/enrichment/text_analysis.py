from __future__ import annotations

import json
import os

from pydantic import BaseModel

from ..model import FileTextAnalysis, ProcessingStage
from ..model.core import FileMetadataBase
from .base import FatalSourceError
from .queries import FileContext

MODEL_ENV = "RPG_LIBRARIAN_LLM_MODEL"
DEFAULT_MODEL = "gpt-5.6-luna"
AGNOSTIC = "Agnostic"
UNKNOWN = "unknown"

_PROMPT = """\
You are analyzing sampled page text from an RPG (tabletop role-playing game)
file to answer two questions about it.

Sampled page text (JSON, keyed by page number):
{sample_text}

Answer with:

- `description`: if the text includes a description of what this file is,
  summarize it in a few sentences. Otherwise leave this blank.
- `possible_system`: the specific RPG system this file is intended for, if you
  can determine one (e.g. "Dungeons & Dragons 5th Edition", "Call of
  Cthulhu"). If the file is clearly system-agnostic (usable with any RPG
  system), use exactly "{agnostic}". If you do not have high
  confidence in either answer, use exactly "{unknown}".
"""


class Judgment(BaseModel):
    description: str | None
    possible_system: str | None


def judge(sample_pages: dict[str, str]) -> Judgment:
    """Ask the configured model for a description and a guess at the system.

    Provider credentials stay in `.env` and are read by litellm from its own
    standard variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...).
    """
    import litellm  # heavy import; only paid when this source actually runs

    prompt = _PROMPT.format(
        sample_text=json.dumps({"pages": sample_pages}),
        agnostic=AGNOSTIC,
        unknown=UNKNOWN,
    )
    try:
        response = litellm.completion(
            model=os.environ.get(MODEL_ENV) or DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=Judgment,
        )
    except (litellm.AuthenticationError, litellm.RateLimitError) as error:
        raise FatalSourceError(f"LLM: {type(error).__name__}: {error}") from error
    return Judgment.model_validate_json(response.choices[0].message.content)


class TextAnalysisSource:
    """Read the stored text sample and record a description and a system guess.

    A file whose sample has no real text gets an empty row without calling the
    model: nothing to reason about, and the row records that it was considered.
    """

    name = "text_analysis"
    stage = ProcessingStage.text_analysis
    table = FileTextAnalysis

    def unavailable_reason(self) -> str | None:
        return None  # credentials are litellm's; a bad one stops the source

    def wants(self, context: FileContext) -> bool:
        return context.sample_pages is not None

    def fetch(self, context: FileContext) -> FileMetadataBase | None:
        pages = context.sample_pages or {}
        if not any(text.strip() for text in pages.values()):
            return FileTextAnalysis(description=None, possible_system=None)
        judgment = judge(pages)
        return FileTextAnalysis(
            description=judgment.description, possible_system=judgment.possible_system
        )
