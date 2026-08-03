"""Command-line access to the catalog tools without an MCP client/LLM in the loop.

Each subcommand drives the same command classes/functions the MCP tools in
``mcp/`` wrap -- this module is just an argparse front end plus JSON output,
built for a human (or a script) sitting at a terminal in the library root.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select

from . import __version__
from .catalog import Catalog
from .commands.ClassifyContentRoleCommand import ClassifyContentRoleCommand
from .commands.FlagForReviewCommand import FlagForReviewCommand
from .commands.LookupIsbnCommand import LookupIsbnCommand
from .commands.LookupRpgGeekProductCommand import LookupRpgGeekProductCommand
from .commands.ReadPdfsCommand import ReadPdfsCommand
from .commands.RemoveCommand import RemoveCommand
from .commands.ResolveReviewFlagCommand import ResolveReviewFlagCommand
from .commands.SearchDtrpgCommand import SearchDtrpgCommand
from .commands.SearchRpgGeekCommand import SearchRpgGeekCommand
from .commands.UpdateCatalogCommand import UpdateCatalogCommand
from .commands.UpdateMetadataCommand import UpdateMetadataCommand
from .commands.UpdateProductCommand import UpdateProductCommand
from .db import session_scope
from .dtrpg import DriveThruRPGClient
from .mcp.directory_status import list_directory_entries, summarize_directories
from .mcp.entry_details import get_entry_details
from .mcp.errors import list_errors
from .mcp.find_duplicates import find_duplicates
from .mcp.ingest_external_source import ingest_external_source
from .mcp.move import move as move_files
from .mcp.readonly_query import get_catalog_schema, run_readonly_query
from .mcp.review_items import list_review_items
from .model import Entry, Error, IdentificationMethod, ProcessingStage
from .progress import CliProgressReporter
from .rpggeek import RpgGeekClient


def _json_default(value: object) -> object:
    if isinstance(value, Path | UUID):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    as_dict = getattr(value, "_asdict", None)
    if callable(as_dict):
        return as_dict()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"not JSON serializable: {value!r}")


def _print(result: Any) -> None:
    print(json.dumps(result, indent=2, default=_json_default))


def _update_result(result: Any) -> dict[str, object]:
    return {**result._asdict(), "errors": [e._asdict() for e in result.errors]}


def _stats(catalog: Catalog) -> dict[str, int]:
    with session_scope(catalog) as session:
        total = session.exec(select(func.count()).select_from(Entry)).one()
        with_product = session.exec(
            select(func.count())
            .select_from(Entry)
            .where(col(Entry.product_id).is_not(None))
        ).one()
        with_errors = session.exec(
            select(func.count(func.distinct(Error.entry_id)))
        ).one()
    return {
        "total_entries": total,
        "with_product": with_product,
        "with_errors": with_errors,
    }


def cmd_stats(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(_stats(catalog))


def cmd_status(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(
        {
            "version": __version__,
            "library_root": str(catalog.library_root),
            "catalog_dir": str(catalog.catalog_dir),
            "catalog_exists": catalog.catalog_dir.is_dir(),
        }
    )


def cmd_update_catalog(args: argparse.Namespace, catalog: Catalog) -> None:
    command = UpdateCatalogCommand(catalog)
    result = asyncio.run(
        command.process(args.path, args.recursive, args.force, CliProgressReporter())
    )
    _print(_update_result(result))


def cmd_update_metadata(args: argparse.Namespace, catalog: Catalog) -> None:
    command = UpdateMetadataCommand(catalog, ProcessingStage.extract_metadata)
    result = asyncio.run(
        command.process(args.path, args.recursive, args.force, CliProgressReporter())
    )
    _print(_update_result(result))


def cmd_read_pdfs(args: argparse.Namespace, catalog: Catalog) -> None:
    command = ReadPdfsCommand(catalog, ProcessingStage.read_pdfs)
    result = asyncio.run(
        command.process(args.path, args.recursive, args.force, CliProgressReporter())
    )
    _print(_update_result(result))


def cmd_classify_content_role(args: argparse.Namespace, catalog: Catalog) -> None:
    command = ClassifyContentRoleCommand(catalog)
    result = asyncio.run(
        command.process(args.path, args.recursive, args.force, CliProgressReporter())
    )
    _print(_update_result(result))


def cmd_remove(args: argparse.Namespace, catalog: Catalog) -> None:
    command = RemoveCommand(catalog)
    result = asyncio.run(
        command.process(args.path, args.recursive, False, CliProgressReporter())
    )
    _print(_update_result(result))


def cmd_flag_for_review(args: argparse.Namespace, catalog: Catalog) -> None:
    command = FlagForReviewCommand(catalog, args.reason)
    result = asyncio.run(
        command.process(args.path, args.recursive, False, CliProgressReporter())
    )
    _print(_update_result(result))


def cmd_resolve_review_flag(args: argparse.Namespace, catalog: Catalog) -> None:
    command = ResolveReviewFlagCommand(catalog, args.note)
    result = asyncio.run(
        command.process(args.path, args.recursive, False, CliProgressReporter())
    )
    _print(_update_result(result))


def cmd_update_product(args: argparse.Namespace, catalog: Catalog) -> None:
    command = UpdateProductCommand(catalog)
    result, product_id, created = asyncio.run(
        command.run(
            args.path,
            args.recursive,
            args.title,
            args.identification_method,
            CliProgressReporter(),
            description=args.description,
            artists=args.artists,
            publisher=args.publisher,
            year=args.year,
            system=args.system,
        )
    )
    _print({**_update_result(result), "product_id": product_id, "created": created})


def cmd_list_entries(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(list_directory_entries(catalog, args.path, args.recursive))


def cmd_summarize_directories(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(summarize_directories(catalog, args.path, args.include_complete, args.limit))


def cmd_list_errors(args: argparse.Namespace, catalog: Catalog) -> None:
    stage = ProcessingStage(args.stage) if args.stage else None
    _print(list_errors(catalog, args.path, stage))


def cmd_list_review_items(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(list_review_items(catalog, args.path))


def cmd_find_duplicates(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(find_duplicates(catalog, args.path))


def cmd_entry_details(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(get_entry_details(catalog, args.path))


def cmd_move(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(move_files(catalog, args.source, args.destination))


def cmd_query(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(run_readonly_query(catalog, args.sql, args.limit))


def cmd_schema(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(get_catalog_schema(catalog))


def cmd_ingest_external_source(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(ingest_external_source(catalog, args.source_path, args.name))


def cmd_lookup_isbn(args: argparse.Namespace, catalog: Catalog) -> None:
    _print(LookupIsbnCommand().run(args.isbn))


def cmd_search_rpg_geek(args: argparse.Namespace, catalog: Catalog) -> None:
    command = SearchRpgGeekCommand(RpgGeekClient())
    _print(asyncio.run(command.run(args.name, args.isbn, args.max_values)))


def cmd_lookup_rpg_geek_product(args: argparse.Namespace, catalog: Catalog) -> None:
    command = LookupRpgGeekProductCommand(RpgGeekClient())
    _print(asyncio.run(command.run(args.rpggeek_id)))


def cmd_search_dtrpg(args: argparse.Namespace, catalog: Catalog) -> None:
    command = SearchDtrpgCommand(DriveThruRPGClient())
    _print(command.run(args.query, args.scope, args.max_values))


def _add_path_recursive_force(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", type=Path)
    parser.add_argument("-r", "--recursive", action="store_true")
    parser.add_argument("--force", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpg-librarian-mcp")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Bring the current directory fully up to date -- create the "
        "catalog/CLAUDE.md/db if missing, upgrade the db schema to the "
        "latest version, and sync CLAUDE.md and bundled skills to the "
        "currently installed version -- then exit instead of starting the "
        "server.",
    )
    subparsers = parser.add_subparsers(dest="command")

    stats = subparsers.add_parser(
        "stats", help="Total entries, entries with a product, entries with an error."
    )
    stats.set_defaults(func=cmd_stats)

    status = subparsers.add_parser("status", help="Server version and library root.")
    status.set_defaults(func=cmd_status)

    update_catalog = subparsers.add_parser(
        "update-catalog", help="Scan a file or directory and update the catalog."
    )
    _add_path_recursive_force(update_catalog)
    update_catalog.set_defaults(func=cmd_update_catalog)

    update_metadata = subparsers.add_parser(
        "update-metadata", help="Extract and persist raw per-source metadata."
    )
    _add_path_recursive_force(update_metadata)
    update_metadata.set_defaults(func=cmd_update_metadata)

    read_pdfs = subparsers.add_parser(
        "read-pdfs", help="Extract barcode/ISBN/sample-text/LLM signal from PDFs."
    )
    _add_path_recursive_force(read_pdfs)
    read_pdfs.set_defaults(func=cmd_read_pdfs)

    classify_content_role = subparsers.add_parser(
        "classify-content-role", help="LLM-classify each entry's product's role."
    )
    _add_path_recursive_force(classify_content_role)
    classify_content_role.set_defaults(func=cmd_classify_content_role)

    remove = subparsers.add_parser(
        "remove", help="Move cataloged entries under a path to .catalog/trash/."
    )
    remove.add_argument("path", type=Path)
    remove.add_argument("-r", "--recursive", action="store_true")
    remove.set_defaults(func=cmd_remove)

    flag_for_review = subparsers.add_parser(
        "flag-for-review", help="Raise an open review flag on entries under a path."
    )
    flag_for_review.add_argument("path", type=Path)
    flag_for_review.add_argument("--reason", required=True)
    flag_for_review.add_argument("-r", "--recursive", action="store_true")
    flag_for_review.set_defaults(func=cmd_flag_for_review)

    resolve_review_flag = subparsers.add_parser(
        "resolve-review-flag", help="Close the open review flag on entries."
    )
    resolve_review_flag.add_argument("path", type=Path)
    resolve_review_flag.add_argument("--note", required=True)
    resolve_review_flag.add_argument("-r", "--recursive", action="store_true")
    resolve_review_flag.set_defaults(func=cmd_resolve_review_flag)

    update_product = subparsers.add_parser(
        "update-product", help="Find or create a Product, then link entries to it."
    )
    update_product.add_argument("path", type=Path)
    update_product.add_argument("--title", required=True)
    update_product.add_argument(
        "--identification-method",
        dest="identification_method",
        required=True,
        choices=[m.value for m in IdentificationMethod],
    )
    update_product.add_argument("-r", "--recursive", action="store_true")
    update_product.add_argument("--description")
    update_product.add_argument("--artists")
    update_product.add_argument("--publisher")
    update_product.add_argument("--year")
    update_product.add_argument("--system")
    update_product.set_defaults(func=cmd_update_product)

    list_entries = subparsers.add_parser(
        "list-entries", help="Files under a path and whether each has a product."
    )
    list_entries.add_argument("path", type=Path)
    list_entries.add_argument("-r", "--recursive", action="store_true")
    list_entries.set_defaults(func=cmd_list_entries)

    summarize_directories_parser = subparsers.add_parser(
        "summarize-directories", help="Per-directory identification counts."
    )
    summarize_directories_parser.add_argument("path", type=Path)
    summarize_directories_parser.add_argument("--include-complete", action="store_true")
    summarize_directories_parser.add_argument("--limit", type=int, default=100)
    summarize_directories_parser.set_defaults(func=cmd_summarize_directories)

    list_errors_parser = subparsers.add_parser(
        "list-errors", help="All recorded processing errors."
    )
    list_errors_parser.add_argument("path", type=Path, nargs="?")
    list_errors_parser.add_argument(
        "--stage", choices=[s.value for s in ProcessingStage]
    )
    list_errors_parser.set_defaults(func=cmd_list_errors)

    list_review_items_parser = subparsers.add_parser(
        "list-review-items", help="All open human-review flags."
    )
    list_review_items_parser.add_argument("path", type=Path, nargs="?")
    list_review_items_parser.set_defaults(func=cmd_list_review_items)

    find_duplicates_parser = subparsers.add_parser(
        "find-duplicates", help="Entries sharing the same content hash."
    )
    find_duplicates_parser.add_argument("path", type=Path, nargs="?")
    find_duplicates_parser.set_defaults(func=cmd_find_duplicates)

    entry_details = subparsers.add_parser(
        "entry-details", help="One entry plus every row linked to it."
    )
    entry_details.add_argument("path", type=Path)
    entry_details.set_defaults(func=cmd_entry_details)

    move_parser = subparsers.add_parser(
        "move", help="Move a file or folder, keeping the catalog in sync."
    )
    move_parser.add_argument("source", type=Path)
    move_parser.add_argument("destination", type=Path)
    move_parser.set_defaults(func=cmd_move)

    query = subparsers.add_parser("query", help="Run one read-only SQL statement.")
    query.add_argument("sql")
    query.add_argument("--limit", type=int, default=500)
    query.set_defaults(func=cmd_query)

    schema = subparsers.add_parser("schema", help="DDL of every domain table.")
    schema.set_defaults(func=cmd_schema)

    ingest = subparsers.add_parser(
        "ingest-external-source", help="Stage new, non-duplicate content."
    )
    ingest.add_argument("source_path", type=Path)
    ingest.add_argument("name")
    ingest.set_defaults(func=cmd_ingest_external_source)

    lookup_isbn = subparsers.add_parser(
        "lookup-isbn", help="Look up bibliographic metadata for an ISBN."
    )
    lookup_isbn.add_argument("isbn")
    lookup_isbn.set_defaults(func=cmd_lookup_isbn)

    search_rpg_geek = subparsers.add_parser(
        "search-rpg-geek", help="Search RPGGeek for candidate products."
    )
    search_rpg_geek.add_argument("--name")
    search_rpg_geek.add_argument("--isbn")
    search_rpg_geek.add_argument("--max-values", type=int, default=5)
    search_rpg_geek.set_defaults(func=cmd_search_rpg_geek)

    lookup_rpg_geek_product = subparsers.add_parser(
        "lookup-rpg-geek-product", help="Fetch full RPGGeek product details."
    )
    lookup_rpg_geek_product.add_argument("rpggeek_id", type=int)
    lookup_rpg_geek_product.set_defaults(func=cmd_lookup_rpg_geek_product)

    search_dtrpg = subparsers.add_parser(
        "search-dtrpg", help="Search DriveThruRPG's catalog or purchased library."
    )
    search_dtrpg.add_argument("query")
    search_dtrpg.add_argument(
        "--scope", choices=["library", "catalog"], default="catalog"
    )
    search_dtrpg.add_argument("--max-values", type=int, default=10)
    search_dtrpg.set_defaults(func=cmd_search_dtrpg)

    return parser


def dispatch(args: argparse.Namespace) -> None:
    catalog = Catalog.from_cwd()
    args.func(args, catalog)
