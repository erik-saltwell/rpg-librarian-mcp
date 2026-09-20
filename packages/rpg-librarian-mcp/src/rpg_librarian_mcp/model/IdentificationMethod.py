from __future__ import annotations

from enum import StrEnum


class IdentificationMethod(StrEnum):
    isbn_match = "isbn_match"
    rpggeek_match = "rpggeek_match"
    drivethru_match = "drivethru_match"
    filename_heuristic = "filename_heuristic"
    llm_judgment = "llm_judgment"
    manual = "manual"
