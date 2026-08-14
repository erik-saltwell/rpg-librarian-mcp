"""Persistent, crash-isolated subprocess pool for risky third-party calls
(trimesh mesh loading, PyMuPDF rendering + tesseract OCR, ...).

Wraps `pebble.ProcessPool`, which already handles the two things bespoke
code would otherwise have to hand-roll: transparently replacing a worker
that crashed (segfault, OOM-kill) or hung past its timeout, without ever
poisoning the pool for later calls the way `concurrent.futures.ProcessPoolExecutor`
does on a single worker death. Workers are also recycled periodically
(`max_tasks`) since long-lived native-library state has been observed to
leak memory across thousands of files even with per-entry `gc.collect()`
in `UpdateBaseCommand` -- see the 2026-08-03 OOM incident (an `update_metadata`
run OOM-killed the whole server process after ~50,000 files).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeoutError
from multiprocessing import get_context
from typing import Any, Protocol

from pebble import ProcessExpired, ProcessPool

_DEFAULT_TIMEOUT_S = 300.0
_DEFAULT_MAX_TASKS = 40


class WorkerPool(Protocol):
    def submit(self, func: Callable[..., Any], *args: Any) -> Any: ...


class IsolatedWorkerPool:
    """Runs `func(*args)` in a persistent worker subprocess.

    `func` and its args/return value must be plain, picklable data -- no
    SQLAlchemy `Entry`/`Session` objects crossing the process boundary.

    On a clean result, returns it. On a genuine exception raised inside
    `func`, re-raises it as-is -- the call happened in a subprocess, but
    the failure is a normal per-file problem (e.g. a corrupt file), not a
    crash, and should be handled exactly like an in-process exception
    would be. On the worker dying (crash) or exceeding `timeout_s` (hang),
    raises `RuntimeError` with the pebble-provided diagnostic; pebble
    transparently replaces the dead/killed worker, so the *next* `submit()`
    just works -- no restart logic needed here.
    """

    def __init__(
        self,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_tasks: int = _DEFAULT_MAX_TASKS,
    ) -> None:
        self._timeout_s = timeout_s
        self._max_tasks = max_tasks
        self._pool: ProcessPool | None = None

    def _get_pool(self) -> ProcessPool:
        # Created lazily, not in __init__ -- constructing a command (and
        # therefore this pool) shouldn't spawn a subprocess before a file
        # of the relevant type is actually seen.
        if self._pool is None:
            self._pool = ProcessPool(
                max_workers=1,
                max_tasks=self._max_tasks,
                context=get_context("spawn"),
            )
        return self._pool

    def submit(self, func: Callable[..., Any], *args: Any) -> Any:
        name = getattr(func, "__name__", repr(func))
        future = self._get_pool().schedule(
            func, args=list(args), timeout=self._timeout_s
        )
        try:
            return future.result()
        except ProcessExpired as exc:
            raise RuntimeError(
                f"{name} worker crashed (exit code {exc.exitcode})"
            ) from exc
        except FutureTimeoutError as exc:
            raise RuntimeError(
                f"{name} exceeded {self._timeout_s:.0f}s and was killed"
            ) from exc

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool.join()
            self._pool = None


class SynchronousWorkerPool:
    """Test double: runs `func(*args)` in-process, no subprocess at all.

    A monkeypatch applied in the test process (e.g. `trimesh.load`,
    `fitz.open`) is invisible to a real subprocess, so tests inject this
    instead of `IsolatedWorkerPool` to keep that pattern working.
    """

    def submit(self, func: Callable[..., Any], *args: Any) -> Any:
        return func(*args)

    def close(self) -> None:
        pass
