"""Wide-event logging for every CLI/MCP call, and for each entry processed
within one.

Two append-only JSON-lines files live in ``.catalog/``:

- ``tool_calls.log`` -- one wide event per CLI subcommand or MCP tool call,
  written by `CallTracker` (used by `ToolCallLoggingMiddleware` for MCP and
  by `cli.dispatch` for the CLI).
- ``entry_processing.log`` -- one wide event per call to
  `UpdateBaseCommand.process_one`, written by `EntryTracker`. A ``started``
  line is written before the call and a ``success``/``error`` line after, so
  tailing the file can distinguish "slow" from "hung": the last line names
  exactly the entry that's in flight.

Business-context fields (counts, ids, external-API tallies, ...) attach to
the *current* event via `log_event_fields` (command-level) and
`log_entry_fields` (entry-level) -- both are no-ops outside of a tracked
call/entry, so deeply nested helper code can call them without knowing
whether it's being driven by the CLI, the MCP server, or a test.
"""

from __future__ import annotations

import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import structlog
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mt

_MAX_VALUE_LEN = 200

TOOL_CALLS_FILENAME = "tool_calls.log"
ENTRY_PROCESSING_FILENAME = "entry_processing.log"

# Set by `configure_wide_event_logs`; None until then (e.g. in tests that
# never call it -- `log_event_fields`/`log_entry_fields` degrade to no-ops,
# and `CallTracker`/`EntryTracker` silently skip writing).
_tool_call_logger: Any | None = None
_entry_logger: Any | None = None
_tool_call_file: IO[str] | None = None
_entry_file: IO[str] | None = None

# See `_event_fields` in the module docstring above: a plain dict, not
# `bind_contextvars` -- FastMCP runs sync tool functions in a worker thread
# via `anyio.to_thread.run_sync`, which copies the *context* into the thread
# but not writes made there back out. `ContextVar.set()` from the worker
# would be invisible to the tracker; mutating the dict object the context
# already points to is visible, since both sides share the same object.
_event_fields: ContextVar[dict[str, Any] | None] = ContextVar(
    "tool_call_event_fields", default=None
)
_entry_fields: ContextVar[dict[str, Any] | None] = ContextVar(
    "entry_event_fields", default=None
)
_current_call_id: ContextVar[str | None] = ContextVar("current_call_id", default=None)
_current_command_name: ContextVar[str | None] = ContextVar(
    "current_command_name", default=None
)


def configure_wide_event_logs(catalog_dir: Path) -> None:
    """Point the two wide-event logs at files under `catalog_dir`.

    Idempotent-ish: safe to call more than once (e.g. across tests that each
    `chdir` into a fresh `tmp_path`) -- closes any previously opened files
    first. Each file is opened once in append mode and kept open for the
    life of the process; every write is flushed immediately (`PrintLogger`
    flushes on every call), so a crash right after a write doesn't lose it.
    """
    global _tool_call_logger, _entry_logger, _tool_call_file, _entry_file

    if _tool_call_file is not None:
        _tool_call_file.close()
    if _entry_file is not None:
        _entry_file.close()

    catalog_dir.mkdir(parents=True, exist_ok=True)
    _tool_call_file = (catalog_dir / TOOL_CALLS_FILENAME).open("a", encoding="utf-8")
    _entry_file = (catalog_dir / ENTRY_PROCESSING_FILENAME).open("a", encoding="utf-8")

    processors = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
    _tool_call_logger = structlog.wrap_logger(
        structlog.PrintLogger(file=_tool_call_file), processors=processors
    )
    _entry_logger = structlog.wrap_logger(
        structlog.PrintLogger(file=_entry_file), processors=processors
    )


def clear_logs(catalog_dir: Path) -> dict[str, bool]:
    """Delete both wide-event log files, then reopen fresh ones in their place.

    Reopening (not just deleting) matters for the MCP server, which keeps
    both files open for its whole lifetime: an unlink alone would leave the
    already-open file descriptors still writing into the now-nameless
    deleted inodes -- freeing the disk space, but silently swallowing every
    event from then on instead of starting a fresh, visible file. No
    locking of any kind is attempted here -- just delete and reopen.
    """
    tool_calls_path = catalog_dir / TOOL_CALLS_FILENAME
    entry_path = catalog_dir / ENTRY_PROCESSING_FILENAME
    tool_calls_existed = tool_calls_path.exists()
    entry_existed = entry_path.exists()

    tool_calls_path.unlink(missing_ok=True)
    entry_path.unlink(missing_ok=True)
    configure_wide_event_logs(catalog_dir)

    return {
        "tool_calls_log_cleared": tool_calls_existed,
        "entry_processing_log_cleared": entry_existed,
    }


def log_event_fields(**fields: Any) -> None:
    """Attach business-context fields to the current command-level event.

    Call this from inside a tool's/command's implementation -- the fields
    show up merged into the single `tool_call` event `CallTracker` emits
    when the call finishes. A no-op outside of a tracked call.
    """
    current = _event_fields.get()
    if current is not None:
        current.update(fields)


def log_entry_fields(**fields: Any) -> None:
    """Attach business-context fields to the current entry-level event.

    Call this from inside `process_one` (or anything it calls) -- the
    fields show up merged into the single `entry_processed` event
    `EntryTracker` emits when the entry finishes. A no-op outside of a
    tracked entry (e.g. commands that aren't entry-scoped at all).
    """
    current = _entry_fields.get()
    if current is not None:
        current.update(fields)


def current_call_id() -> str | None:
    """The `call_id` of the enclosing `CallTracker`, if any."""
    return _current_call_id.get()


def current_command_name() -> str | None:
    """The normalized command name of the enclosing `CallTracker`, if any."""
    return _current_command_name.get()


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


class CallTracker:
    """Tracks one CLI subcommand or MCP tool call for `tool_calls.log`.

    Usage::

        with CallTracker("read_pdfs", transport="cli") as tracker:
            tracker.event_fields["arguments"] = {...}
            ... do the call ...

    On a clean exit, emits a ``success`` event. On an exception, emits an
    ``error`` event with the exception type/message *and a full traceback*
    -- unlike per-entry errors (which are routine and already persisted to
    the `Error` table), an exception reaching this level means the whole
    run aborted, which is exactly the "why is it crashing" case a
    traceback is for. The exception always propagates (this is not a
    swallow-and-continue mechanism).
    """

    def __init__(self, command: str, transport: str) -> None:
        self.command = command.replace("-", "_")
        self.transport = transport
        self.call_id = str(uuid.uuid4())
        self.event_fields: dict[str, Any] = {}
        self.outcome: str | None = None
        self.error_message: str | None = None
        self._start = time.perf_counter()
        self._start_time = datetime.now(UTC).isoformat()
        self._fields_token: Any = None
        self._call_id_token: Any = None
        self._command_token: Any = None

    def mark_error(self, error_message: str | None = None) -> None:
        """Record a failure that isn't an exception (e.g. an MCP tool
        result with `is_error=True`)."""
        self.outcome = "error"
        if error_message:
            self.error_message = error_message

    def __enter__(self) -> CallTracker:
        self._fields_token = _event_fields.set(self.event_fields)
        self._call_id_token = _current_call_id.set(self.call_id)
        self._command_token = _current_command_name.set(self.command)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        error_type: str | None = None
        traceback_str: str | None = None
        error_message = self.error_message
        outcome = self.outcome or "success"

        if exc_type is not None:
            outcome = "error"
            error_type = exc_type.__name__
            error_message = str(exc)
            traceback_str = "".join(traceback.format_exception(exc_type, exc, tb))

        event: dict[str, Any] = {
            "command": self.command,
            "transport": self.transport,
            "call_id": self.call_id,
            "start_time": self._start_time,
            "duration_ms": round((time.perf_counter() - self._start) * 1000, 2),
            "outcome": outcome,
            **self.event_fields,
        }
        if error_type is not None:
            event["error_type"] = error_type
        if error_message is not None:
            event["error_message"] = error_message[:_MAX_VALUE_LEN]
        if traceback_str is not None:
            event["traceback"] = traceback_str

        if _tool_call_logger is not None:
            _tool_call_logger.msg("tool_call", **event)

        _event_fields.reset(self._fields_token)
        _current_call_id.reset(self._call_id_token)
        _current_command_name.reset(self._command_token)
        return False


class EntryTracker:
    """Tracks one `UpdateBaseCommand.process_one` call for
    `entry_processing.log`.

    Writes a ``started`` line on entry (before `process_one` runs) and a
    ``success``/``error`` line on exit -- the pairing is what makes "is it
    hung" answerable by tailing the file: the last line names exactly the
    entry in flight, and its age tells you how long it's been stuck there.

    Entry-level errors never carry a traceback (unlike `CallTracker`'s
    abort case): per-entry failures are routine (a bad PDF, no ISBN match)
    and already persisted to the `Error` table with their own context: a
    traceback repeated per failed file would just be noise.
    """

    def __init__(self, command: str, entry_id: Any, entry_path: Path) -> None:
        self.command = command
        self.entry_id = entry_id
        self.entry_path = entry_path
        self.call_id = current_call_id()
        self.entry_fields: dict[str, Any] = {}
        self._start = time.perf_counter()
        self._start_time = datetime.now(UTC).isoformat()
        self._fields_token: Any = None

    def _base_fields(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "call_id": self.call_id,
            "entry_id": str(self.entry_id) if self.entry_id is not None else None,
            "entry_path": str(self.entry_path),
            "start_time": self._start_time,
        }

    def __enter__(self) -> EntryTracker:
        self._fields_token = _entry_fields.set(self.entry_fields)
        if _entry_logger is not None:
            _entry_logger.msg(
                "entry_processed", **self._base_fields(), outcome="started"
            )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        event: dict[str, Any] = {
            **self._base_fields(),
            "duration_ms": round((time.perf_counter() - self._start) * 1000, 2),
            "outcome": "error" if exc_type is not None else "success",
            **self.entry_fields,
        }
        if exc_type is not None:
            event["error_type"] = exc_type.__name__
            event["error_message"] = str(exc)[:_MAX_VALUE_LEN]

        if _entry_logger is not None:
            _entry_logger.msg("entry_processed", **event)

        _entry_fields.reset(self._fields_token)
        return False


def _log_lightweight_entry(
    command: str, entry_id: Any, entry_path: Path, outcome: str, **extra: Any
) -> None:
    if _entry_logger is None:
        return
    _entry_logger.msg(
        "entry_processed",
        command=command,
        call_id=current_call_id(),
        entry_id=str(entry_id) if entry_id is not None else None,
        entry_path=str(entry_path),
        start_time=datetime.now(UTC).isoformat(),
        outcome=outcome,
        **extra,
    )


def log_entry_skipped(
    command: str, entry_id: Any, entry_path: Path, **extra: Any
) -> None:
    """A lightweight line for an entry that was skipped (`process_one` never
    ran) -- just enough to confirm the file was seen and why nothing
    happened, without the start/duration bookkeeping a real attempt gets.
    `extra` fields (e.g. `existing_lookup_ms`) merge into the same line."""
    _log_lightweight_entry(command, entry_id, entry_path, outcome="skipped", **extra)


def log_entry_error(
    command: str, entry_id: Any, entry_path: Path, error_message: str
) -> None:
    """A lightweight line for an entry rejected before any real attempt was
    made (e.g. a path too shallow to ever be cataloged) -- no `started`
    line precedes it since there was nothing to time, unlike `EntryTracker`."""
    _log_lightweight_entry(
        command,
        entry_id,
        entry_path,
        outcome="error",
        error_message=error_message[:_MAX_VALUE_LEN],
    )


class ToolCallLoggingMiddleware(Middleware):
    """Emits one wide event per ``tools/call``, success or failure."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        tool_name = context.message.name
        arguments = _summarize_arguments(context.message.arguments)

        with CallTracker(tool_name, transport="mcp") as tracker:
            tracker.event_fields["arguments"] = arguments
            result = await call_next(context)
            if bool(getattr(result, "is_error", False)):
                content = getattr(result, "content", None)
                error_message = str(content[0])[:_MAX_VALUE_LEN] if content else None
                tracker.mark_error(error_message)
            return result
