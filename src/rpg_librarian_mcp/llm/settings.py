from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml


@lru_cache(maxsize=1)
def llm_model() -> str:
    """The litellm model string, from the bundled (checked-in) settings file.

    Provider API keys are deliberately not read here -- they stay in `.env`
    and are read directly by litellm from its own standard env vars (e.g.
    OPENAI_API_KEY/ANTHROPIC_API_KEY).
    """
    resource = resources.files("rpg_librarian_mcp") / "resources" / "llm_settings.yaml"
    settings = yaml.safe_load(resource.read_text(encoding="utf-8"))
    return settings["model"]
