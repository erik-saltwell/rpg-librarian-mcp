from __future__ import annotations

from pathlib import Path
from typing import Any

from pymediainfo import MediaInfo

from .base import ExtractionResult


def extract(path: Path) -> ExtractionResult:
    try:
        media_info = MediaInfo.parse(path)
    except Exception:
        return ExtractionResult()

    media_type_metadata: dict[str, Any] = {}
    base_metadata: dict[str, str] = {}

    general = next(iter(media_info.general_tracks), None)
    if general is not None:
        duration_ms = getattr(general, "duration", None)
        if duration_ms:
            media_type_metadata["duration_seconds"] = float(duration_ms) / 1000

        title = getattr(general, "title", None)
        artist = getattr(general, "performer", None)
        comment = getattr(general, "comment", None)
        if title:
            media_type_metadata["title"] = title
            base_metadata["title"] = title
        if artist:
            media_type_metadata["artist"] = artist
            base_metadata["artist"] = artist
        if comment:
            media_type_metadata["comment"] = comment

    video_track = next(iter(media_info.video_tracks), None)
    if video_track is not None:
        width = getattr(video_track, "width", None)
        height = getattr(video_track, "height", None)
        if width:
            media_type_metadata["width"] = int(width)
        if height:
            media_type_metadata["height"] = int(height)

    media_type_metadata["has_audio"] = len(media_info.audio_tracks) > 0

    return ExtractionResult(media_type_metadata=media_type_metadata, base_metadata=base_metadata)
