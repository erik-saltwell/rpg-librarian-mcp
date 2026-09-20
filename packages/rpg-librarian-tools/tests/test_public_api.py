from pathlib import Path

from rpg_librarian_tools.files import MediaType, inspect_file
from rpg_librarian_tools.identifiers import IdentifierKind, find_publication_identifiers


def test_find_publication_identifiers_returns_all_matches_in_source_order() -> None:
    found = find_publication_identifiers("ISSN 2049-3630, ISBN 978-0-306-40615-7")

    assert [identifier.kind for identifier in found] == [
        IdentifierKind.ISSN,
        IdentifierKind.ISBN,
    ]
    assert [identifier.value for identifier in found] == [
        "20493630",
        "9780306406157",
    ]


def test_inspect_file_returns_all_cataloging_signals(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")

    result = inspect_file(path)

    assert result.size_in_bytes == 5
    assert len(result.sha256) == 64
    assert result.media_type is MediaType.text
