"""CLI mirrors of the MCP tools: the same services, printed as JSON.

They let the whole surface be exercised (and scripted) without an MCP client.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..db import session_scope
from ..model import Disposition
from ..services import lists, reports
from ..services.serialize import to_jsonable
from ..services.update_product import PRODUCT_METADATA_FIELDS, UpdateProductRequest
from ..services.update_product import update_product as apply_update_product


def _emit(data: Any) -> int:
    print(json.dumps(to_jsonable(data), indent=2, ensure_ascii=False))
    return 0


def update_product(args: argparse.Namespace, catalog_path: Path) -> int:
    metadata = {
        key: getattr(args, key)
        for key in PRODUCT_METADATA_FIELDS
        if getattr(args, key) is not None
    }
    request = UpdateProductRequest(
        file_ids=args.file_ids,
        disposition=Disposition(args.disposition) if args.disposition else None,
        product_type=args.product_type,
        product_line=args.product_line,
        product=args.product,
        product_metadata=metadata or None,
        create_line=args.create_line,
        create_type=args.create_type,
        aliases=args.alias or [],
        review_flag=args.review_flag,
        note=args.note,
    )
    with session_scope(catalog_path) as session:
        return _emit(apply_update_product(session, request))


def report_file(args: argparse.Namespace, catalog_path: Path) -> int:
    with session_scope(catalog_path) as session:
        return _emit(reports.report_file(session, args.file_id))


def report_product(args: argparse.Namespace, catalog_path: Path) -> int:
    with session_scope(catalog_path) as session:
        return _emit(
            reports.report_product(
                session,
                product_id=args.id,
                product_type=args.product_type,
                product_line=args.product_line,
                product=args.product,
            )
        )


def report_line(args: argparse.Namespace, catalog_path: Path) -> int:
    with session_scope(catalog_path) as session:
        return _emit(
            reports.report_line(
                session,
                line_id=args.id,
                product_type=args.product_type,
                product_line=args.product_line,
            )
        )


def list_unfiled(args: argparse.Namespace, catalog_path: Path) -> int:
    with session_scope(catalog_path) as session:
        return _emit(
            lists.list_unfiled(
                session,
                folder=args.folder,
                root_id=args.root_id,
                recursive=args.recursive,
                include_flagged=args.include_flagged,
                limit=args.limit,
            )
        )


def list_types(args: argparse.Namespace, catalog_path: Path) -> int:
    with session_scope(catalog_path) as session:
        return _emit(lists.list_product_types(session))


def list_lines(args: argparse.Namespace, catalog_path: Path) -> int:
    with session_scope(catalog_path) as session:
        return _emit(
            lists.list_product_lines(
                session,
                product_type=args.product_type,
                search=args.search,
                limit=args.limit,
            )
        )
