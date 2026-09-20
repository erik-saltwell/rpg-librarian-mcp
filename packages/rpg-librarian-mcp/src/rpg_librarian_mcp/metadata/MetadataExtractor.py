from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from rpg_librarian_mcp.model import FileMetadata

_artist_key: str = "artist"
_title_key: str = "title"
_publisher_key: str = "publisher"
_copyright_key: str = "copyright"
_genre_key: str = "genre"
_isbn_key: str = "isbn"
_issn_key: str = "issn"


_candidate_names: dict[str, list[str]] = {
    _artist_key: [
        "artist",
        "artists",
        "creator",
        "author",
        "authors",
        "performer",
        "performers",
    ],
    _title_key: ["title", "album", "track"],
    _publisher_key: ["publisher", "organization"],
    _copyright_key: ["copyright", "year", "date"],
    _genre_key: ["genre"],
    _isbn_key: ["isbn"],
    _issn_key: ["issn"],
}


class MetadataExtractor(ABC):
    def extract_file_metadata(self) -> FileMetadata:
        artist: str | None = self.extract_from_candidates(_candidate_names[_artist_key])
        title: str | None = self.extract_from_candidates(_candidate_names[_title_key])
        publisher: str | None = self.extract_from_candidates(
            _candidate_names[_publisher_key]
        )
        copyright: str | None = self.extract_from_candidates(
            _candidate_names[_copyright_key]
        )
        return FileMetadata(
            title=title, artist=artist, publisher=publisher, copyright=copyright
        )

    def extract_from_candidates(self, candidates: Iterable[str]) -> str | None:
        for candidate in candidates:
            potential_value = self.extract_value(candidate)
            if potential_value:
                return potential_value
        return None

    def extract_isbn(self) -> str | None:
        return self.extract_from_candidates(_candidate_names[_isbn_key])

    def extract_issn(self) -> str | None:
        return self.extract_from_candidates(_candidate_names[_issn_key])

    def extract_genre(self) -> str | None:
        return self.extract_from_candidates(_candidate_names[_genre_key])

    @abstractmethod
    def extract_value(self, field: str) -> str | None: ...

    @abstractmethod
    def extract_custom_metadata(self) -> Any | None: ...
