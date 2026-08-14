from pathlib import Path

from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.mcp.clear_metadata import clear_metadata
from rpg_librarian_mcp.model import (
    AudioMetadata,
    Entry,
    FileMetadata,
    ImageMetadata,
    MeshMetadata,
    PdfContents,
    PdfMetadata,
    VideoMetadata,
)

FAKE_SHA = "a" * 64


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


def _make_entry(session, parent_path: str, filename: str) -> Entry:
    entry = Entry(
        parent_path=Path(parent_path),
        filename=filename,
        sha256=FAKE_SHA,
        size_in_bytes=10,
        mime_type="text/plain",
        media_type="text",
    )
    session.add(entry)
    session.flush()
    return entry


def test_clear_metadata_deletes_generic_and_every_type_specific_table(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        pdf_entry = _make_entry(session, "shelf/box", "book.pdf")
        session.add(FileMetadata(entry_id=pdf_entry.id, title="Book"))
        session.add(PdfMetadata(entry_id=pdf_entry.id, page_count=5))
        image_entry = _make_entry(session, "shelf/box", "map.jpg")
        session.add(ImageMetadata(entry_id=image_entry.id, width=10))
        video_entry = _make_entry(session, "shelf/box", "recap.mp4")
        session.add(VideoMetadata(entry_id=video_entry.id, duration_seconds=10))
        audio_entry = _make_entry(session, "shelf/box", "track.mp3")
        session.add(AudioMetadata(entry_id=audio_entry.id, duration_seconds=10))
        mesh_entry = _make_entry(session, "shelf/box", "mini.stl")
        session.add(MeshMetadata(entry_id=mesh_entry.id, unit="mm"))
        session.commit()
        pdf_entry_id = pdf_entry.id
        image_entry_id = image_entry.id
        video_entry_id = video_entry.id
        audio_entry_id = audio_entry.id
        mesh_entry_id = mesh_entry.id

    result = clear_metadata(catalog)

    assert result == {
        "file_metadata": 1,
        "pdf_metadata": 1,
        "image_metadata": 1,
        "video_metadata": 1,
        "audio_metadata": 1,
        "mesh_metadata": 1,
    }
    with session_scope(catalog) as session:
        assert session.get(FileMetadata, pdf_entry_id) is None
        assert session.get(PdfMetadata, pdf_entry_id) is None
        assert session.get(ImageMetadata, image_entry_id) is None
        assert session.get(VideoMetadata, video_entry_id) is None
        assert session.get(AudioMetadata, audio_entry_id) is None
        assert session.get(MeshMetadata, mesh_entry_id) is None
        # Entry rows themselves are untouched.
        assert session.get(Entry, pdf_entry_id) is not None


def test_clear_metadata_leaves_pdf_contents_alone(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        entry = _make_entry(session, "shelf/box", "book.pdf")
        session.add(FileMetadata(entry_id=entry.id, title="Book"))
        session.add(PdfContents(entry_id=entry.id, sample_text="hello"))
        session.commit()
        entry_id = entry.id

    clear_metadata(catalog)

    with session_scope(catalog) as session:
        assert session.get(FileMetadata, entry_id) is None
        assert session.get(PdfContents, entry_id) is not None


def test_clear_metadata_returns_zero_counts_when_nothing_to_clear(tmp_path):
    catalog = _catalog(tmp_path)

    result = clear_metadata(catalog)

    assert result == {
        "file_metadata": 0,
        "pdf_metadata": 0,
        "image_metadata": 0,
        "video_metadata": 0,
        "audio_metadata": 0,
        "mesh_metadata": 0,
    }
