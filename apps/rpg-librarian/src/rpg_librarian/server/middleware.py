from __future__ import annotations

from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mt

from ..observability import CallTracker

_MAX_ERROR_LEN = 200


class ToolCallLoggingMiddleware(Middleware):
    """Emits one wide event per `tools/call`, success or failure."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        with CallTracker(
            context.message.name,
            transport="mcp",
            arguments=context.message.arguments,
            log_start=False,
        ) as tracker:
            result = await call_next(context)
            if bool(getattr(result, "is_error", False)):
                content = getattr(result, "content", None)
                message = str(content[0])[:_MAX_ERROR_LEN] if content else None
                tracker.mark_error(message)
            return result
