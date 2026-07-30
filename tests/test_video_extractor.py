from pathlib import Path
from types import SimpleNamespace

from rpg_librarian_mcp.metadata.extractors import video_extractor
from rpg_librarian_mcp.metadata.extractors.video_extractor import VideoExtractor
from rpg_librarian_mcp.model import VideoMetadata


def test_extract_custom_metadata_returns_video_dimensions_duration_and_audio_flag(
    monkeypatch,
):
    media_info = SimpleNamespace(
        general_tracks=[],
        video_tracks=[SimpleNamespace(duration="12345", width="1920", height="1080")],
        audio_tracks=[SimpleNamespace()],
    )
    monkeypatch.setattr(
        video_extractor.MediaInfo,
        "parse",
        lambda filename: media_info,
    )

    metadata = VideoExtractor(Path("trailer.mp4")).extract_custom_metadata()

    assert isinstance(metadata, VideoMetadata)
    assert metadata.duration_seconds == 12.345
    assert metadata.width == 1920
    assert metadata.height == 1080
    assert metadata.has_audio is True
