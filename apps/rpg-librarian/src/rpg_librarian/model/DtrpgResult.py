from __future__ import annotations

from .core import EvidenceBase


class DtrpgResult(EvidenceBase, table=True):
    """DriveThruRPG catalog search hits.

    `results` holds the top products: id, title, description, publisher, authors,
    and game system.
    """

    __tablename__ = "dtrpg_result"
