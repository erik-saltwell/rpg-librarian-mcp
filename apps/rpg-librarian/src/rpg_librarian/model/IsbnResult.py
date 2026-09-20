from __future__ import annotations

from .core import EvidenceBase


class IsbnResult(EvidenceBase, table=True):
    """The bibliographic record for the file's ISBN.

    `results` holds at most one record (title, authors, publisher, year,
    description) and which provider found it.
    """

    __tablename__ = "isbn_result"
