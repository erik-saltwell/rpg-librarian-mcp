from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ._isbn import isbn, issn


class IdentifierKind(StrEnum):
    ISBN = "isbn"
    ISSN = "issn"


class IdentifierSource(StrEnum):
    TEXT = "text"
    BARCODE = "barcode"


@dataclass(frozen=True, slots=True)
class PublicationIdentifier:
    kind: IdentifierKind
    value: str
    source: IdentifierSource
    raw_value: str
    page: int | None = None


def find_publication_identifiers(text: str) -> tuple[PublicationIdentifier, ...]:
    """Return every checksum-valid ISBN and ISSN in source order."""
    matches: list[tuple[int, PublicationIdentifier]] = []
    for module, kind in ((isbn, IdentifierKind.ISBN), (issn, IdentifierKind.ISSN)):
        for match in module._CORE_PATTERN.finditer(text):
            raw = match.group(0)
            value = module._normalize(module._clean(raw))
            if module._validate(value):
                matches.append(
                    (
                        match.start(),
                        PublicationIdentifier(
                            kind=kind,
                            value=value,
                            source=IdentifierSource.TEXT,
                            raw_value=raw,
                        ),
                    )
                )
    matches.sort(key=lambda item: item[0])
    return tuple(identifier for _, identifier in matches)


def _decode_publication_barcode(value: str, page: int) -> PublicationIdentifier | None:
    if (normalized := isbn.from_ean13(value)) is not None or isbn.validate(value):
        return PublicationIdentifier(
            IdentifierKind.ISBN,
            normalized or isbn._normalize(value),
            IdentifierSource.BARCODE,
            value,
            page,
        )
    if (normalized := issn.from_ean13(value)) is not None or issn.validate(value):
        return PublicationIdentifier(
            IdentifierKind.ISSN,
            normalized or issn._normalize(value),
            IdentifierSource.BARCODE,
            value,
            page,
        )
    return None
