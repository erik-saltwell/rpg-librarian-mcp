from __future__ import annotations

from functools import lru_cache
from importlib import resources

import litellm
from jinja2 import Template
from pydantic import BaseModel

from ..model.ContentRole import ContentRole
from .settings import llm_model


class ContentRoleLlmJudgment(BaseModel):
    content_role: ContentRole


@lru_cache(maxsize=1)
def _prompt_template() -> Template:
    resource = (
        resources.files("rpg_librarian_mcp")
        / "resources"
        / "prompts"
        / "content_role_prompt.jinja"
    )
    return Template(resource.read_text(encoding="utf-8"))


def judge_content_role(context_text: str) -> ContentRoleLlmJudgment:
    """Ask the configured LLM to classify a product's content role.

    `context_text` is the product's description plus any linked PDFs'
    sample text/description, already gathered by the caller -- this
    function does no extraction of its own.

    `litellm.AuthenticationError`/`litellm.RateLimitError` are allowed to
    propagate uncaught, same as `judge_pdf_contents` -- the caller marks
    these fatal (aborting the whole run) rather than per-entry.
    """
    prompt = _prompt_template().render(
        context_text=context_text, roles=list(ContentRole)
    )
    response = litellm.completion(
        model=llm_model(),
        messages=[{"role": "user", "content": prompt}],
        response_format=ContentRoleLlmJudgment,
    )
    content = response.choices[0].message.content
    return ContentRoleLlmJudgment.model_validate_json(content)
