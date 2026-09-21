"""Wide-event logging: one append-only JSON-lines stream, ``logs/events.log``.

The stream sits in a `logs/` directory beside the catalog. A batch verb (`scan`,
`enrich`) reads top to bottom as its own story, joined by a shared `call_id`:

1. ``call_started`` -- once, when the verb begins, with its arguments.
2. ``file`` -- exactly one per file handled, whatever happened to it: ``success``,
   ``error``, or ``skipped``. Everything known about the file is on that one line
   (path, duration, hashes, page counts, which `enrich` source, the error).
3. ``call_finished`` -- once, when the verb ends, with its totals and outcome. It is
   written on failure and on Ctrl-C too, so a run that dies still says how it ended.
   A ``call_started`` with no ``call_finished`` means the process was killed hard.

An MCP tool call is a single ``call_finished`` event: a tool call is one operation,
so it has no start entry and no per-file events.

Business-context fields attach to the *current* event through `log_call_fields` and
`log_file_fields`; both are no-ops outside a tracked call or file, so nested helpers
can call them without knowing who is driving. `mark_file_error` records that the
current file failed in a way that did not raise (scan stores stage errors in the
`error` table and carries on).
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

_MAX_VALUE_LEN = 200
LOGS_DIRNAME = "logs"
EVENTS_FILENAME = "events.log"

_logger: Any | None = None
_events_file: IO[str] | None = None

# Plain dicts held in context variables, mutated in place: a worker thread that
# copies the context still shares the dict object, so writes made there show up.
_call_fields: ContextVar[dict[str, Any] | None] = ContextVar(
    "call_fields", default=None
)
_file_fields: ContextVar[dict[str, Any] | None] = ContextVar(
    "file_fields", default=None
)
_current_file: ContextVar[FileTracker | None] = ContextVar("current_file", default=None)
_current_call_id: ContextVar[str | None] = ContextVar("current_call_id", default=None)
_current_command: ContextVar[str | None] = ContextVar("current_command", default=None)


def logs_dir_for(catalog_path: Path) -> Path:
    return catalog_path.parent / LOGS_DIRNAME


def configure_wide_event_logs(catalog_path: Path) -> None:
    """Point the event stream at a file beside `catalog_path`. Safe to repeat."""
    global _logger, _events_file

    if _events_file is not None:
        _events_file.close()

    logs_dir = logs_dir_for(catalog_path)
    logs_dir.mkdir(parents=True, exist_ok=True)
    _events_file = (logs_dir / EVENTS_FILENAME).open("a", encoding="utf-8")
    _logger = structlog.wrap_logger(
        structlog.PrintLogger(file=_events_file),
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


def _emit(event: str, **fields: Any) -> None:
    if _logger is not None:
        _logger.msg(event, **fields)


def log_call_fields(**fields: Any) -> None:
    """Attach fields to the current call's ``call_finished`` event; no-op outside."""
    current = _call_fields.get()
    if current is not None:
        current.update(fields)


def log_file_fields(**fields: Any) -> None:
    """Attach fields to the current file's event; no-op outside a file."""
    current = _file_fields.get()
    if current is not None:
        current.update(fields)


def mark_file_error(message: str | None = None) -> None:
    """Record that the current file failed without raising; no-op outside a file."""
    tracker = _current_file.get()
    if tracker is not None:
        tracker.mark_error(message)


def current_call_id() -> str | None:
    return _current_call_id.get()


def current_command() -> str | None:
    return _current_command.get()


def summarize_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
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
    """Tracks one CLI verb or MCP tool call.

    Emits ``call_started`` on entry (unless `log_start` is False) and
    ``call_finished`` on exit. An exception ends the call with outcome ``error``,
    the type and message, and a full traceback (an exception reaching here aborted
    the whole run, which is the case a traceback is for), and then propagates.
    """

    def __init__(
        self,
        command: str,
        transport: str,
        *,
        arguments: dict[str, Any] | None = None,
        log_start: bool = True,
    ) -> None:
        self.command = command.replace("-", "_")
        self.transport = transport
        self.arguments = summarize_arguments(arguments)
        self.log_start = log_start
        self.call_id = str(uuid.uuid4())
        self.fields: dict[str, Any] = {}
        self.outcome: str | None = None
        self.error_message: str | None = None
        self._start = time.perf_counter()
        self._start_time = datetime.now(UTC).isoformat()
        self._tokens: list[Any] = []

    def mark_error(self, error_message: str | None = None) -> None:
        """Record a failure that is not an exception (an MCP `is_error` result)."""
        self.outcome = "error"
        if error_message:
            self.error_message = error_message

    def _identity(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "transport": self.transport,
            "call_id": self.call_id,
            "start_time": self._start_time,
            "arguments": self.arguments,
        }

    def __enter__(self) -> CallTracker:
        self._tokens = [
            _call_fields.set(self.fields),
            _current_call_id.set(self.call_id),
            _current_command.set(self.command),
        ]
        if self.log_start:
            _emit("call_started", **self._identity())
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        event: dict[str, Any] = {
            **self._identity(),
            "duration_ms": round((time.perf_counter() - self._start) * 1000, 2),
            **self.fields,
        }
        outcome = self.outcome or "success"
        if exc_type is not None:
            outcome = "error"
            event["error_type"] = exc_type.__name__
            event["error_message"] = str(exc)[:_MAX_VALUE_LEN]
            event["traceback"] = "".join(traceback.format_exception(exc_type, exc, tb))
        elif self.error_message is not None:
            event["error_message"] = self.error_message[:_MAX_VALUE_LEN]
        event["outcome"] = outcome
        _emit("call_finished", **event)

        for var, token in zip(
            (_call_fields, _current_call_id, _current_command),
            self._tokens,
            strict=True,
        ):
            var.reset(token)
        return False


class FileTracker:
    """Tracks the handling of one file and emits its single ``file`` event on exit.

    Extra keyword fields (for example `source` for `enrich`) go on that one event.
    An exception ends it with outcome ``error``; so does `mark_error`. File-level
    errors carry no traceback: they are routine (a bad PDF) and are also persisted to
    the `error` table.
    """

    def __init__(self, file_id: int | None, path: Path, **fields: Any) -> None:
        self.file_id = file_id
        self.path = path
        self.fields: dict[str, Any] = dict(fields)
        self.outcome: str | None = None
        self.error_message: str | None = None
        self._start = time.perf_counter()
        self._start_time = datetime.now(UTC).isoformat()
        self._tokens: list[Any] = []

    def mark_error(self, message: str | None = None) -> None:
        self.outcome = "error"
        if message and self.error_message is None:
            self.error_message = message

    def __enter__(self) -> FileTracker:
        self._tokens = [_file_fields.set(self.fields), _current_file.set(self)]
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        event: dict[str, Any] = {
            "command": current_command(),
            "call_id": current_call_id(),
            "file_id": self.file_id,
            "path": str(self.path),
            "start_time": self._start_time,
            "duration_ms": round((time.perf_counter() - self._start) * 1000, 2),
            **self.fields,
        }
        outcome = self.outcome or "success"
        if exc_type is not None:
            outcome = "error"
            event["error_type"] = exc_type.__name__
            event["error_message"] = str(exc)[:_MAX_VALUE_LEN]
        elif self.error_message is not None:
            event["error_message"] = self.error_message[:_MAX_VALUE_LEN]
        event["outcome"] = outcome
        _emit("file", **event)

        _file_fields.reset(self._tokens[0])
        _current_file.reset(self._tokens[1])
        return False


def log_file_skipped(file_id: int | None, path: Path, **extra: Any) -> None:
    """The single event for a file that was seen but needed no work."""
    _emit(
        "file",
        command=current_command(),
        call_id=current_call_id(),
        file_id=file_id,
        path=str(path),
        start_time=datetime.now(UTC).isoformat(),
        outcome="skipped",
        **extra,
    )
