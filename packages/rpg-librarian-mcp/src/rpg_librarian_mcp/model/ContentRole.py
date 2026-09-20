from __future__ import annotations

from enum import StrEnum


class ContentRole(StrEnum):
    core_rules = "core_rules"
    adventures_and_scenarios = "adventures_and_scenarios"
    settings_and_supplements = "settings_and_supplements"
    gm_and_player_aids = "gm_and_player_aids"
    extras = "extras"
