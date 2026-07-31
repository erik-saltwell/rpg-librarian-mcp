"""MCP-facing tool modules.

Each module exposes ``register(mcp, config)`` and is listed in ``REGISTRARS``.
Adding a tool group is: new module + one line here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fastmcp import FastMCP

from ..catalog import Catalog
from . import (
    classify_content_role,
    directory_status,
    dtrpg,
    errors,
    find_duplicates,
    ingest_external_source,
    isbn,
    metadata,
    move,
    read_pdfs,
    readonly_query,
    remove,
    rpg_geek,
    status,
    update_catalog,
    update_product,
)

Registrar = Callable[[FastMCP, Catalog], None]

REGISTRARS: Sequence[Registrar] = (
    status.register,
    update_catalog.register,
    directory_status.register,
    errors.register,
    find_duplicates.register,
    readonly_query.register,
    move.register,
    remove.register,
    metadata.register,
    read_pdfs.register,
    rpg_geek.register,
    dtrpg.register,
    isbn.register,
    update_product.register,
    ingest_external_source.register,
    classify_content_role.register,
)

__all__ = [
    "REGISTRARS",
    "Registrar",
]
