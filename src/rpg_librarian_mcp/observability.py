"""Wide-event logging for every MCP tool call.

One structlog event per call, emitted when the call finishes, carrying what
happened (tool, arguments, outcome, error) and how long it took.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any

import structlog
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mt

log = structlog.get_logger("rpg_librarian_mcp.tool_call")

_MAX_VALUE_LEN = 200

# Holds the in-flight call's field dict so `log_event_fields` can add to it
# from inside a tool's implementation. A plain dict, not `bind_contextvars`:
# FastMCP runs sync tool functions in a worker thread via
# `anyio.to_thread.run_sync`, which copies the *context* into the thread but
# not writes made there back out. `ContextVar.set()` from the worker would be
# invisible to the middleware; mutating the dict object the context already
# points to is visible, since both sides share the same object.
_event_fields: ContextVar[dict[str, Any] | None] = ContextVar(
    "tool_call_event_fields", default=None
)


def log_event_fields(**fields: Any) -> None:
    """Attach business-context fields (counts, ids, etc.) to the current tool
    call's wide event.

    Call this from inside a tool's implementation -- the fields show up
    merged into the single `tool_call` event `ToolCallLoggingMiddleware`
    emits when the call finishes. A no-op outside of a tool call.
    """
    current = _event_fields.get()
    if current is not None:
        current.update(fields)


def _summarize_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Truncate long string arguments so wide events stay readable."""
    if not arguments:
        return {}
    summary: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > _MAX_VALUE_LEN:
            summary[key] = f"{value[:_MAX_VALUE_LEN]}...(len={len(value)})"
        else:
            summary[key] = value
    return summary


class ToolCallLoggingMiddleware(Middleware):
    """Emits one wide event per ``tools/call``, success or failure."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        tool_name = context.message.name
        arguments = _summarize_arguments(context.message.arguments)
        start = time.perf_counter()
        event_fields: dict[str, Any] = {}
        token = _event_fields.set(event_fields)

        try:
            try:
                result = await call_next(context)
            except Exception as exc:
                error_event: dict[str, Any] = {
                    "tool": tool_name,
                    "arguments": arguments,
                    "outcome": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    **event_fields,
                }
                log.info("tool_call", **error_event)
                raise

            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            is_error = bool(getattr(result, "is_error", False))
            event: dict[str, Any] = {
                "tool": tool_name,
                "arguments": arguments,
                "outcome": "error" if is_error else "success",
                "duration_ms": duration_ms,
                **event_fields,
            }
            if is_error:
                content = getattr(result, "content", None)
                if content:
                    event["error_message"] = str(content[0])[:_MAX_VALUE_LEN]
            log.info("tool_call", **event)
            return result
        finally:
            _event_fields.reset(token)
