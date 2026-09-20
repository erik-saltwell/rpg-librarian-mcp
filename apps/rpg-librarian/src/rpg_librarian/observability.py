"""Wide-event logging: one JSON line per CLI call, and one per file processed.

Two append-only JSON-lines files live in a `logs/` directory beside the catalog:

- ``calls.log`` -- one wide event per CLI verb (later also per MCP tool call),
  written by `CallTracker`.
- ``files.log`` -- one wide event per file a verb processes, written by
  `FileTracker`. A ``started`` line precedes the work and a ``success``/``error``
  line follows it, so tailing the file tells "slow" from "hung": the last line
  names the file in flight.

Business-context fields attach to the *current* event through `log_call_fields`
and `log_file_fields`; both are no-ops outside a tracked call or file, so nested
helpers can call them without knowing who is driving.
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
CALLS_FILENAME = "calls.log"
FILES_FILENAME = "files.log"

_call_logger: Any | None = None
_file_logger: Any | None = None
_call_file: IO[str] | None = None
_file_file: IO[str] | None = None

# Plain dicts held in context variables, mutated in place: a worker thread that
# copies the context still shares the dict object, so writes made there show up.
_call_fields: ContextVar[dict[str, Any] | None] = ContextVar(
    "call_fields", default=None
)
_file_fields: ContextVar[dict[str, Any] | None] = ContextVar(
    "file_fields", default=None
)
_current_call_id: ContextVar[str | None] = ContextVar("current_call_id", default=None)
_current_command: ContextVar[str | None] = ContextVar("current_command", default=None)


def logs_dir_for(catalog_path: Path) -> Path:
    return catalog_path.parent / LOGS_DIRNAME


def configure_wide_event_logs(catalog_path: Path) -> None:
    """Point both logs at files beside `catalog_path`. Safe to call repeatedly."""
    global _call_logger, _file_logger, _call_file, _file_file

    if _call_file is not None:
        _call_file.close()
    if _file_file is not None:
        _file_file.close()

    logs_dir = logs_dir_for(catalog_path)
    logs_dir.mkdir(parents=True, exist_ok=True)
    _call_file = (logs_dir / CALLS_FILENAME).open("a", encoding="utf-8")
    _file_file = (logs_dir / FILES_FILENAME).open("a", encoding="utf-8")

    processors = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
    _call_logger = structlog.wrap_logger(
        structlog.PrintLogger(file=_call_file), processors=processors
    )
    _file_logger = structlog.wrap_logger(
        structlog.PrintLogger(file=_file_file), processors=processors
    )


def log_call_fields(**fields: Any) -> None:
    """Attach fields to the current call-level event; no-op outside a call."""
    current = _call_fields.get()
    if current is not None:
        current.update(fields)


def log_file_fields(**fields: Any) -> None:
    """Attach fields to the current file-level event; no-op outside a file."""
    current = _file_fields.get()
    if current is not None:
        current.update(fields)


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
    """Tracks one CLI verb or MCP tool call for `calls.log`.

    A clean exit emits ``success``; an exception emits ``error`` with the type,
    message, and a full traceback (an exception reaching here aborted the whole
    run, which is the case a traceback is for) and then propagates.
    """

    def __init__(self, command: str, transport: str) -> None:
        self.command = command.replace("-", "_")
        self.transport = transport
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

    def __enter__(self) -> CallTracker:
        self._tokens = [
            _call_fields.set(self.fields),
            _current_call_id.set(self.call_id),
            _current_command.set(self.command),
        ]
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        outcome = self.outcome or "success"
        event: dict[str, Any] = {
            "command": self.command,
            "transport": self.transport,
            "call_id": self.call_id,
            "start_time": self._start_time,
            "duration_ms": round((time.perf_counter() - self._start) * 1000, 2),
            **self.fields,
        }
        if exc_type is not None:
            outcome = "error"
            event["error_type"] = exc_type.__name__
            event["error_message"] = str(exc)[:_MAX_VALUE_LEN]
            event["traceback"] = "".join(traceback.format_exception(exc_type, exc, tb))
        elif self.error_message is not None:
            event["error_message"] = self.error_message[:_MAX_VALUE_LEN]
        event["outcome"] = outcome

        if _call_logger is not None:
            _call_logger.msg("call", **event)

        for var, token in zip(
            (_call_fields, _current_call_id, _current_command),
            self._tokens,
            strict=True,
        ):
            var.reset(token)
        return False


class FileTracker:
    """Tracks the processing of one file for `files.log`.

    File-level errors carry no traceback: they are routine (a bad PDF) and are
    already persisted to the `error` table.
    """

    def __init__(self, file_id: int | None, path: Path) -> None:
        self.file_id = file_id
        self.path = path
        self.fields: dict[str, Any] = {}
        self._start = time.perf_counter()
        self._start_time = datetime.now(UTC).isoformat()
        self._token: Any = None

    def _base_fields(self) -> dict[str, Any]:
        return {
            "command": current_command(),
            "call_id": current_call_id(),
            "file_id": self.file_id,
            "path": str(self.path),
            "start_time": self._start_time,
        }

    def __enter__(self) -> FileTracker:
        self._token = _file_fields.set(self.fields)
        if _file_logger is not None:
            _file_logger.msg("file", **self._base_fields(), outcome="started")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        event: dict[str, Any] = {
            **self._base_fields(),
            "duration_ms": round((time.perf_counter() - self._start) * 1000, 2),
            "outcome": "error" if exc_type is not None else "success",
            **self.fields,
        }
        if exc_type is not None:
            event["error_type"] = exc_type.__name__
            event["error_message"] = str(exc)[:_MAX_VALUE_LEN]
        if _file_logger is not None:
            _file_logger.msg("file", **event)
        _file_fields.reset(self._token)
        return False


def log_file_skipped(file_id: int | None, path: Path, **extra: Any) -> None:
    """One light line for a file that was seen but needed no work."""
    if _file_logger is None:
        return
    _file_logger.msg(
        "file",
        command=current_command(),
        call_id=current_call_id(),
        file_id=file_id,
        path=str(path),
        start_time=datetime.now(UTC).isoformat(),
        outcome="skipped",
        **extra,
    )
