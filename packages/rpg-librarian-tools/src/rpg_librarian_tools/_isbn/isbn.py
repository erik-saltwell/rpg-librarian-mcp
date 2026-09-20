from __future__ import annotations

import re

from barcode import ISBN10, ISBN13
from barcode.errors import BarcodeError

_CORE_PATTERN = re.compile(
    r"(?<![0-9X])"
    r"(?:"
    r"97[89][- ]?[0-9]{10}|"
    r"97[89][- ][- 0-9]{13}|"
    r"[0-9]{9}[0-9X]|"
    r"[0-9]{1,5}[- ][0-9]{1,7}[- ][0-9]{1,6}[- ]?[0-9X]|"
    r"[-0-9X]{10,16}"
    r")"
    r"(?![0-9X])",
    re.I | re.M | re.S,
)

_LEGAL_CHARS = set("0123456789xX- ")


def extract(text: str) -> str | None:
    for candidate in _collect(text):
        cleaned = _clean(candidate)
        normalized = _normalize(cleaned)
        if _validate(normalized):
            return normalized
    return None


def validate(text: str) -> bool:
    """Whether `text` is a valid ISBN-10 or ISBN-13 (checksum included)."""
    return _validate(text)


def from_ean13(code: str) -> str | None:
    """The ISBN-13 encoded by an EAN-13 barcode, or None.

    A "Bookland" EAN-13 (prefix 978/979) simply is the ISBN-13,
    checksum included.
    """
    normalized = _normalize(code)
    if (
        len(normalized) == 13
        and normalized.startswith(("978", "979"))
        and _validate(normalized)
    ):
        return normalized
    return None


def _collect(text: str) -> list[str]:
    """
    Collect all ISBN-like strings from the given text.

    Args:
        text (str): The text to search for ISBN-like strings.
    """
    return re.findall(_CORE_PATTERN, text)


def _clean(isbnlike: str) -> str:
    """Strip everything except legal ISBN characters (digits, x/X,
    hyphens, and spaces).

    Then normalize whitespace around hyphens and collapse repeated
    spaces, mirroring isbnlib.clean().
    """
    # Keep only characters that could legitimately appear in an
    # ISBN-like string. _CORE_PATTERN never matches letters, so this
    # is just a defensive filter, not a label stripper.
    filtered = "".join(c for c in isbnlike if c in _LEGAL_CHARS)

    # Collapse "  -  " / " - " / "-  " etc. down to a bare "-"
    filtered = re.sub(r"\s*-\s*", "-", filtered)

    # Collapse any remaining runs of whitespace to a single space
    filtered = re.sub(r"\s+", " ", filtered)

    return filtered.strip().upper()


def _normalize(text: str) -> str:
    """Strip hyphens and spaces, producing the canonical digit-only
    (plus check-digit "X") form used both to validate an ISBN and to
    return it, so the same physical ISBN always yields the same
    string regardless of how it was separated in the source text.
    """
    return text.replace("-", "").replace(" ", "").upper()


def _validate(text: str) -> bool:
    """
    Check if the given text is a valid ISBN-10 or ISBN-13.

    Args:
        text (str): The text to check.
    """
    normalized = _normalize(text)
    if set(normalized) == {"0"}:
        # An all-zero body trivially satisfies any checksum (every weighted
        # term is zero), so it must be rejected explicitly -- it's always a
        # misread barcode/OCR artifact, never a real ISBN.
        return False
    barcode_type = {10: ISBN10, 13: ISBN13}.get(len(normalized))
    if barcode_type is None:
        return False

    try:
        # Pass the normalized form: python-barcode strips hyphens itself
        # but rejects spaces, and its computed check digit is uppercase.
        return str(barcode_type(normalized)) == normalized
    except BarcodeError, TypeError, ValueError:
        return False
