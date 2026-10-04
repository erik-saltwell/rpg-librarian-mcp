"""Ask the model which of a batch of sibling folders are packs.

Uses the same model setting and credentials as the text-analysis source
(`RPG_LIBRARIAN_LLM_MODEL`; provider keys read by litellm from `.env`).
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..enrichment.base import FatalSourceError
from ..enrichment.text_analysis import DEFAULT_MODEL, MODEL_ENV

_PROMPT = """\
You are organizing a library of tabletop RPG files. Decide, for each folder listed
below, whether it is a *pack*.

- `pack`: the folder holds ONE release (one product) whose files have no identity of
  their own: a map pack, a token set, an audio or music pack, an STL/miniature set, an
  art or asset pack. Its subfolders are sections or variants of that release (Day/Night,
  Gridded/Gridless, PNG/JPG, Tokens and Maps of the same product). A short PDF or text
  file inside (license, readme, guide) is part of the pack. Numbered runs of similar
  names and variant subfolders are strong signs of a pack.
- `container`: the folder holds several distinct releases further down (a category such
  as "Maps", a publisher, a game, a bundle). List in `descend_into` the subfolder names
  that may hold packs. Subfolders not shown (`more_subfolders`) are always examined.
- `no_packs`: nothing at or below this folder is a pack (books, rules documents,
  unrelated loose files).

`search` holds Google results for the folder's name. Treat them as corroboration only:
a generic name can match unrelated products, and no results do not argue against a
pack. Prefer the folder structure and file names.

The folders share the parent folder {parent!r}. Answer once for every folder, using its
exact `folder` value, with a short reason.

Folders (JSON):
{folders}
"""


class FolderAnswer(BaseModel):
    folder: str
    decision: Literal["pack", "container", "no_packs"]
    reason: str
    descend_into: list[str] = Field(default_factory=list)


class Answers(BaseModel):
    folders: list[FolderAnswer]


def model_name() -> str:
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


def judge(parent: str, folders: list[dict[str, Any]]) -> list[FolderAnswer]:
    """One model call for a batch of sibling folders' evidence summaries."""
    import litellm  # heavy import; only paid when find-packs actually asks

    prompt = _PROMPT.format(
        parent=parent or "(the top of a source folder)",
        folders=json.dumps(folders, ensure_ascii=False, indent=1),
    )
    try:
        response = litellm.completion(
            model=model_name(),
            messages=[{"role": "user", "content": prompt}],
            response_format=Answers,
        )
    except (litellm.AuthenticationError, litellm.RateLimitError) as error:
        raise FatalSourceError(f"LLM: {type(error).__name__}: {error}") from error
    return Answers.model_validate_json(response.choices[0].message.content).folders
