"""MCP-facing tool modules.

Each module exposes ``register(mcp, config)`` and is listed in ``REGISTRARS``.
Adding a tool group is: new module + one line here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fastmcp import FastMCP

from ..catalog import Catalog
from . import status, update_catalog

Registrar = Callable[[FastMCP, Catalog], None]

REGISTRARS: Sequence[Registrar] = (status.register, update_catalog.register)

__all__ = [
    "REGISTRARS",
    "Registrar",
]
