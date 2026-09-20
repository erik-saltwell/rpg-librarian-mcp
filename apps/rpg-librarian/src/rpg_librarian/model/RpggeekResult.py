from __future__ import annotations

from .core import EvidenceBase


class RpggeekResult(EvidenceBase, table=True):
    """RPGGeek search candidates; the first also carries its product details."""

    __tablename__ = "rpggeek_result"
