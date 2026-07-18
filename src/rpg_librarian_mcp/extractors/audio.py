from __future__ import annotations

from pathlib import Path

import mutagen

from .base import ExtractionResult

# mutagen "easy" tag key -> universal base-metadata field.
_EASY_TAG_FIELDS = {
    "artist": "artist",
    "title": "title",
    "album": "publisher",
    "genre": "genre",
}


def extract(path: Path) -> ExtractionResult:
    media_type_metadata: dict[str, float | None] = {"duration": None}
    base_metadata: dict[str, str] = {}

    try:
        audio_file = mutagen.File(path, easy=True)
    except Exception:
        audio_file = None

    if audio_file is not None:
        if audio_file.info is not None and getattr(audio_file.info, "length", None) is not None:
            media_type_metadata["duration"] = float(audio_file.info.length)
        for tag_key, base_field in _EASY_TAG_FIELDS.items():
            values = audio_file.get(tag_key) if audio_file.tags else None
            if values:
                base_metadata[base_field] = str(values[0])

    return ExtractionResult(media_type_metadata=media_type_metadata, base_metadata=base_metadata)
