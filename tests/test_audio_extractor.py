from pathlib import Path

from rpg_librarian_mcp.metadata.extractors import audio_extractor
from rpg_librarian_mcp.metadata.extractors.audio_extractor import AudioExtractor
from rpg_librarian_mcp.model import AudioMetadata


class _Info:
    length = 42.4249


class _Audio:
    info = _Info()

    def items(self):
        return [("genre", ["Dungeon Synth"])]


def test_extract_custom_metadata_returns_duration_and_genre(monkeypatch):
    monkeypatch.setattr(audio_extractor, "_open_audio", lambda file_path: _Audio())

    metadata = AudioExtractor(Path("song.mp3")).extract_custom_metadata()

    assert isinstance(metadata, AudioMetadata)
    assert metadata.duration_seconds == 42.425
    assert metadata.genre == "Dungeon Synth"
