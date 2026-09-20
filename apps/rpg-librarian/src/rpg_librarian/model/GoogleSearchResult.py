from __future__ import annotations

from .core import EvidenceBase


class GoogleSearchResult(EvidenceBase, table=True):
    """Top Google hits for the file, fetched through Serper.

    `results` holds position, title, URL, and snippet per hit.
    """

    __tablename__ = "google_search_result"
