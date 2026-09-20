from pathlib import Path

from sqlmodel import select

from conftest import insert_raw_entry
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry
from rpg_librarian_mcp.model.MediaType import MediaType


def test_reading_an_unrecognized_media_type_degrades_to_unknown(tmp_path):
    """Bug 1, root cause: a row with a media_type outside the enum must not
    raise on read -- it should read back as MediaType.unknown."""
    catalog = Catalog(library_root=tmp_path)
    insert_raw_entry(
        catalog,
        parent_path=".",
        filename="canary.pdf",
        media_type="document",
        mime_type="application/pdf",
    )

    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()

    assert len(entries) == 1
    assert entries[0].media_type == MediaType.unknown


def test_reading_a_valid_media_type_is_unaffected(tmp_path):
    catalog = Catalog(library_root=tmp_path)
    insert_raw_entry(
        catalog,
        parent_path="shelf/box",
        filename="book.pdf",
        media_type="pdf",
        mime_type="application/pdf",
    )

    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()

    assert entries[0].media_type == MediaType.pdf


def test_writing_a_media_type_still_round_trips(tmp_path):
    catalog = Catalog(library_root=tmp_path)
    with session_scope(catalog) as session:
        session.add(
            Entry(
                parent_path=Path("shelf/box"),
                filename="book.txt",
                sha256="a" * 64,
                size_in_bytes=10,
                mime_type="text/plain",
                media_type=MediaType.text,
            )
        )
        session.commit()

    with session_scope(catalog) as session:
        entries = session.exec(select(Entry)).all()

    assert entries[0].media_type == MediaType.text
