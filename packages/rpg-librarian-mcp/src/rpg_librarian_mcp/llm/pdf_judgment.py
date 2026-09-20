from __future__ import annotations

from functools import lru_cache
from importlib import resources

import litellm
from jinja2 import Template
from pydantic import BaseModel

from ..model.Product import Product
from .settings import llm_model


class PdfLlmJudgment(BaseModel):
    description: str | None
    possible_system: str | None


@lru_cache(maxsize=1)
def _prompt_template() -> Template:
    resource = (
        resources.files("rpg_librarian_mcp")
        / "resources"
        / "prompts"
        / "pdf_llm_prompt.jinja"
    )
    return Template(resource.read_text(encoding="utf-8"))


def judge_pdf_contents(sample_text: str) -> PdfLlmJudgment:
    """Ask the configured LLM for `description`/`possible_system` from sampled text.

    Callers should skip this entirely when `sample_text` has no real
    content -- there's nothing for the LLM to reason about, and the
    sentinel-default answer it would give back can be filled in for free.

    `litellm.AuthenticationError`/`litellm.RateLimitError` are allowed to
    propagate uncaught -- neither is likely to resolve on the next entry, so
    the caller (`ReadPdfsCommand`) should let these abort the whole run
    rather than catching them per-entry like other extraction failures.
    """
    prompt = _prompt_template().render(
        sample_text=sample_text,
        agnostic_sentinel=Product.AGNOSTIC,
        unknown_sentinel=Product.UNKNOWN_SYSTEM,
    )
    response = litellm.completion(
        model=llm_model(),
        messages=[{"role": "user", "content": prompt}],
        response_format=PdfLlmJudgment,
    )
    content = response.choices[0].message.content
    return PdfLlmJudgment.model_validate_json(content)
