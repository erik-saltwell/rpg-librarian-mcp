from __future__ import annotations

import re

_CORE_PATTERN = re.compile(
    r"(?<![0-9X])"
    r"[0-9]{4}[- ]?[0-9]{3}[0-9X]"
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


def _collect(text: str) -> list[str]:
    """
    Collect all ISSN-like strings from the given text.

    Args:
        text (str): The text to search for ISSN-like strings.
    """
    return re.findall(_CORE_PATTERN, text)


def _clean(issnlike: str) -> str:
    """Strip everything except legal ISSN characters (digits, x/X,
    hyphens, and spaces).

    Then normalize whitespace around hyphens and collapse repeated
    spaces, mirroring isbnlib.clean().
    """
    # Keep only characters that could legitimately appear in an
    # ISSN-like string. _CORE_PATTERN never matches letters, so this
    # is just a defensive filter, not a label stripper.
    filtered = "".join(c for c in issnlike if c in _LEGAL_CHARS)

    # Collapse "  -  " / " - " / "-  " etc. down to a bare "-"
    filtered = re.sub(r"\s*-\s*", "-", filtered)

    # Collapse any remaining runs of whitespace to a single space
    filtered = re.sub(r"\s+", " ", filtered)

    return filtered.strip().upper()


def _normalize(text: str) -> str:
    """Strip hyphens and spaces, producing the canonical digit-only
    (plus check-digit "X") form used both to validate an ISSN and to
    return it, so the same physical ISSN always yields the same
    string regardless of how it was separated in the source text.
    """
    return text.replace("-", "").replace(" ", "").upper()


def _check_digit(body: str) -> str:
    """The mod-11 check digit for a 7-digit ISSN body.

    Computed directly: python-barcode's ISSN class returns "11" instead
    of "0" when the weighted sum is divisible by 11, wrongly rejecting
    valid ISSNs such as 2049-3630.
    """
    remainder = sum(int(d) * w for d, w in zip(body, range(8, 1, -1), strict=True)) % 11
    return "0" if remainder == 0 else "X" if remainder == 1 else str(11 - remainder)


def _validate(text: str) -> bool:
    """
    Check if the given text is a valid ISSN.

    Args:
        text (str): The text to check.
    """
    normalized = _normalize(text)
    if len(normalized) != 8 or not normalized[:7].isdigit():
        return False
    if set(normalized) == {"0"}:
        # An all-zero body trivially satisfies the mod-11 checksum (every
        # weighted term is zero), so it must be rejected explicitly -- it's
        # always a misread barcode/OCR artifact, never a real ISSN.
        return False
    return normalized[7] == _check_digit(normalized[:7])


def validate(text: str) -> bool:
    """Whether `text` is a valid ISSN (checksum included)."""
    return _validate(text)


def from_ean13(code: str) -> str | None:
    """The ISSN encoded by an EAN-13 barcode with the serial prefix 977, or None.

    A 977 EAN-13 carries the 7-digit ISSN body in digits 4-10 (the ISSN's
    own check digit is replaced by a 2-digit price/variant code and the
    EAN checksum), so the ISSN check digit must be recomputed.
    """
    normalized = _normalize(code)
    if (
        len(normalized) != 13
        or not normalized.isdigit()
        or not normalized.startswith("977")
    ):
        return None

    evens = sum(int(d) for d in normalized[0:12:2])
    odds = sum(int(d) for d in normalized[1:12:2])
    if (10 - (evens + odds * 3) % 10) % 10 != int(normalized[12]):
        return None

    body = normalized[3:10]
    result = f"{body}{_check_digit(body)}"
    return result if _validate(result) else None
