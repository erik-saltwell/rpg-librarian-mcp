"""MCP-facing tool modules.

Each module exposes ``register(mcp, config)`` and is listed in ``REGISTRARS``.
Adding a tool group is: new module + one line here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fastmcp import FastMCP

from ..catalog import Catalog
from . import (
    directory_status,
    dtrpg,
    errors,
    isbn,
    metadata,
    move,
    read_pdfs,
    readonly_query,
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
    readonly_query.register,
    move.register,
    metadata.register,
    read_pdfs.register,
    rpg_geek.register,
    dtrpg.register,
    isbn.register,
    update_product.register,
)

__all__ = [
    "REGISTRARS",
    "Registrar",
]
