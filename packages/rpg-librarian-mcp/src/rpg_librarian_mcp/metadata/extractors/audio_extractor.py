from __future__ import annotations

from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen import FileType, MutagenError
from mutagen.easyid3 import EasyID3

from ...model import AudioMetadata
from ..MetadataExtractor import MetadataExtractor

type AudioFile = FileType | EasyID3


def get_duration(audio_file: Any) -> float | None:
    info = getattr(audio_file, "info", None)
    return round(info.length, 3) if info and hasattr(info, "length") else None


def _open_audio(file_path: Path) -> AudioFile | None:
    try:
        audio_file = MutagenFile(file_path, easy=True)
    except MutagenError:
        audio_file = None

    if audio_file is not None:
        return audio_file

    try:
        return EasyID3(file_path)
    except MutagenError:
        return None


class AudioExtractor(MetadataExtractor):
    def __init__(self, file_path: Path) -> None:
        self._audio: AudioFile | None = _open_audio(file_path=file_path)

    def extract_value(self, field: str) -> str | None:
        if self._audio is None:
            return None
        key = field.lower()
        for tag_key, tag_value in self._audio.items():
            if tag_key.lower() == key:
                values = tag_value if isinstance(tag_value, list) else [tag_value]
                for v in values:
                    text = str(v).strip()
                    if text:
                        return text
        return None

    def extract_custom_metadata(self) -> Any | None:
        return AudioMetadata(
            duration_seconds=get_duration(self._audio), genre=self.extract_genre()
        )
