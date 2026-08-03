import json
from pathlib import Path

import pytest

from rpg_librarian_mcp.__main__ import main
from rpg_librarian_mcp.catalog import Catalog
from rpg_librarian_mcp.cli import _stats, build_parser
from rpg_librarian_mcp.db import session_scope
from rpg_librarian_mcp.model import Entry, Error, IdentificationMethod, Product
from rpg_librarian_mcp.model.ProcessingStage import ProcessingStage

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


def test_stats_counts_total_with_product_and_with_errors(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        _make_entry(session, "shelf/box", "unidentified.txt")
        product = Product(
            title="Some Book", identification_method=IdentificationMethod.manual
        )
        session.add(product)
        session.flush()
        with_product = _make_entry(session, "shelf/box", "identified.txt")
        with_product.product_id = product.id
        session.add(with_product)
        errored = _make_entry(session, "shelf/box", "broken.txt")
        session.add(
            Error(
                entry_id=errored.id,
                stage=ProcessingStage.extract_metadata,
                error_text="boom",
            )
        )
        session.commit()

    assert _stats(catalog) == {
        "total_entries": 3,
        "with_product": 1,
        "with_errors": 1,
    }


def test_stats_counts_an_entry_once_even_with_multiple_error_stages(tmp_path):
    catalog = _catalog(tmp_path)
    with session_scope(catalog) as session:
        entry = _make_entry(session, "shelf/box", "broken.txt")
        session.add(
            Error(
                entry_id=entry.id,
                stage=ProcessingStage.extract_metadata,
                error_text="boom",
            )
        )
        session.add(
            Error(entry_id=entry.id, stage=ProcessingStage.read_pdfs, error_text="boom")
        )
        session.commit()

    assert _stats(catalog)["with_errors"] == 1


def test_stats_command_prints_json(tmp_path, monkeypatch, capsys):
    catalog = _catalog(tmp_path)
    catalog.catalog_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["rpg-librarian-mcp", "stats"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"total_entries": 0, "with_product": 0, "with_errors": 0}


def test_status_command_reports_library_root(tmp_path, monkeypatch, capsys):
    catalog = _catalog(tmp_path)
    catalog.catalog_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["rpg-librarian-mcp", "status"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["library_root"] == str(tmp_path.resolve())
    assert payload["catalog_exists"] is True


@pytest.mark.parametrize(
    "argv",
    [
        ["stats"],
        ["status"],
        ["update-catalog", "/tmp/x"],
        ["update-metadata", "/tmp/x"],
        ["read-pdfs", "/tmp/x"],
        ["classify-content-role", "/tmp/x"],
        ["remove", "/tmp/x"],
        ["flag-for-review", "/tmp/x", "--reason", "r"],
        ["resolve-review-flag", "/tmp/x", "--note", "n"],
        [
            "update-product",
            "/tmp/x",
            "--title",
            "t",
            "--identification-method",
            "manual",
        ],
        ["list-entries", "/tmp/x"],
        ["summarize-directories", "/tmp/x"],
        ["list-errors"],
        ["list-review-items"],
        ["find-duplicates"],
        ["entry-details", "/tmp/x"],
        ["move", "/tmp/x", "/tmp/y"],
        ["query", "select 1"],
        ["schema"],
        ["ingest-external-source", "/tmp/x", "name"],
        ["lookup-isbn", "9780765326355"],
        ["search-rpg-geek", "--name", "n"],
        ["lookup-rpg-geek-product", "1"],
        ["search-dtrpg", "q"],
    ],
)
def test_every_subcommand_parses_and_dispatches_to_a_handler(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    assert callable(args.func)


def test_no_subcommand_leaves_command_none():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.command is None


def test_migrate_flag_still_works_alongside_subcommands():
    parser = build_parser()
    args = parser.parse_args(["--migrate"])
    assert args.migrate is True
    assert args.command is None
