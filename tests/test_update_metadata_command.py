from pathlib import Path

from sqlmodel import select

from conftest import FakeProgressReporter
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.commands.UpdateCatalogCommand import UpdateCatalogCommand
from rpg_librarian_mcp.commands.UpdateMetadataCommand import UpdateMetadataCommand
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import (
    AudioMetadata,
    Entry,
    Error,
    FileMetadata,
    ProcessingStage,
)


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(library_root=tmp_path)


async def _catalog_file(tmp_path: Path, parent: str, filename: str, text: str) -> Path:
    shelf = tmp_path / parent
    shelf.mkdir(parents=True, exist_ok=True)
    file_path = shelf / filename
    file_path.write_text(text)
    catalog = _catalog(tmp_path)
    await UpdateCatalogCommand(catalog).process(
        tmp_path, True, False, FakeProgressReporter()
    )
    return file_path


def _get_entry(catalog: Catalog, filename: str) -> Entry:
    with session_scope(catalog) as session:
        return session.exec(select(Entry).where(Entry.filename == filename)).one()


async def test_process_one_persists_generic_and_type_specific_metadata(
    tmp_path, monkeypatch
):
    """A plain-text file has no real audio content, but media_type is forced
    to `audio` here so the type-specific side table (AudioMetadata) is
    exercised too, alongside the always-present FileMetadata row."""
    await _catalog_file(tmp_path, "shelf/box", "song.mp3", "not really audio")
    catalog = _catalog(tmp_path)
    entry = _get_entry(catalog, "song.mp3")

    class _FakeExtractor:
        def extract_file_metadata(self):
            return FileMetadata(title="Dungeon Synth Vol. 1", artist="Someone")

        def extract_custom_metadata(self):
            return AudioMetadata(duration_seconds=42.4, genre="Dungeon Synth")

    monkeypatch.setattr(
        "rpg_librarian_mcp.commands.UpdateMetadataCommand.generate_extractor",
        lambda media_type, file_path, mesh_pool=None: _FakeExtractor(),
    )
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.succeeded == 1
    assert result.errored == 0
    with session_scope(catalog) as session:
        file_metadata = session.get(FileMetadata, entry.id)
        assert file_metadata is not None
        assert file_metadata.title == "Dungeon Synth Vol. 1"
        assert file_metadata.artist == "Someone"

        audio_metadata = session.get(AudioMetadata, entry.id)
        assert audio_metadata is not None
        assert audio_metadata.duration_seconds == 42.4
        assert audio_metadata.genre == "Dungeon Synth"


async def test_process_one_skips_the_type_specific_table_when_none(tmp_path):
    """A real cataloged .txt file has media_type == text, which
    generate_extractor routes to NoMetadataExtractor -- extract_value always
    returns None (empty FileMetadata) and extract_custom_metadata returns
    None (nothing to upsert into a type-specific table)."""
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello world")
    catalog = _catalog(tmp_path)
    entry = _get_entry(catalog, "book.txt")
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.succeeded == 1
    with session_scope(catalog) as session:
        file_metadata = session.get(FileMetadata, entry.id)
        assert file_metadata is not None
        assert file_metadata.title is None
        assert session.exec(select(AudioMetadata)).all() == []


async def test_should_process_is_true_when_no_file_metadata_exists(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    entry = _get_entry(catalog, "book.txt")
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)

    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is True


async def test_should_process_is_false_once_file_metadata_exists_with_no_error(
    tmp_path,
):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    entry = _get_entry(catalog, "book.txt")
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)
    await command.process(tmp_path, True, False, FakeProgressReporter())

    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is False


async def test_should_process_is_true_again_when_an_error_row_exists(tmp_path):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)
    entry = _get_entry(catalog, "book.txt")
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)
    await command.process(tmp_path, True, False, FakeProgressReporter())
    with session_scope(catalog) as session:
        session.add(
            Error(
                entry_id=entry.id,
                stage=ProcessingStage.extract_metadata,
                error_text="stale failure",
            )
        )
        session.commit()

    with session_scope(catalog) as session:
        assert command.should_process(session, entry) is True


async def test_corrupted_pdf_is_recorded_as_an_error_not_a_silent_success(tmp_path):
    """Bug 3 (errors.md #3): a PDF with a valid header/footer but garbage
    body previously made `fitz.open` raise inside PdfExtractor.__init__,
    which was swallowed -- the entry was reported as succeeded with an
    all-NULL PdfMetadata row, and nothing showed up in list_errors."""
    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True)
    (shelf / "garbage.pdf").write_text("%PDF-1.4\nnot a real pdf body\n%%EOF")
    catalog = _catalog(tmp_path)
    await UpdateCatalogCommand(catalog).process(
        tmp_path, True, False, FakeProgressReporter()
    )
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.succeeded == 0
    assert result.errored == 1
    with session_scope(catalog) as session:
        errors = session.exec(select(Error)).all()
        assert len(errors) == 1
        assert errors[0].stage == ProcessingStage.extract_metadata


async def test_lys_mesh_file_is_not_errored(tmp_path):
    """Bug (errors.md): .lys (Lychee Slicer project) is classified as
    media_type=mesh, so it's routed to MeshExtractor, but trimesh doesn't
    actually support the format and raises NotImplementedError -- surfacing
    as an errored entry instead of succeeding with no type-specific metadata,
    unlike read_pdfs's skip-not-error handling of non-matching file types.

    Real .lys files are zip containers (like .3mf), so mime sniffing falls
    back to the extension -- a real zip archive is written here so the file
    is classified as media_type=mesh the same way, rather than text."""
    import zipfile

    shelf = tmp_path / "shelf" / "box"
    shelf.mkdir(parents=True)
    with zipfile.ZipFile(shelf / "model.lys", "w") as zf:
        zf.writestr("not_a_real_model", "placeholder")
    catalog = _catalog(tmp_path)
    await UpdateCatalogCommand(catalog).process(
        tmp_path, True, False, FakeProgressReporter()
    )
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 0
    assert result.succeeded == 1
    with session_scope(catalog) as session:
        assert session.exec(select(Error)).all() == []


async def test_extractor_failure_is_recorded_as_an_error(tmp_path, monkeypatch):
    await _catalog_file(tmp_path, "shelf/box", "book.txt", "hello")
    catalog = _catalog(tmp_path)

    def _raise(media_type, file_path, mesh_pool=None):
        raise ValueError("unreadable file")

    monkeypatch.setattr(
        "rpg_librarian_mcp.commands.UpdateMetadataCommand.generate_extractor", _raise
    )
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)

    result = await command.process(tmp_path, True, False, FakeProgressReporter())

    assert result.errored == 1
    assert result.errors[0].reason == "unreadable file"
    with session_scope(catalog) as session:
        errors = session.exec(select(Error)).all()
        assert len(errors) == 1
        assert errors[0].stage == ProcessingStage.extract_metadata
        assert session.exec(select(FileMetadata)).all() == []
