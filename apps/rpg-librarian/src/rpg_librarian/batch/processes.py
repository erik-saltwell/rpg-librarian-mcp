"""Own one process group so interruption cannot leave our agent writing behind us."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import ExitStack, suppress
from pathlib import Path


def stop_group(group_id: int) -> None:
    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.killpg(group_id, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    with suppress(ProcessLookupError):
        os.killpg(group_id, signal.SIGKILL)


def execute(
    command: list[str],
    *,
    stdout: Path,
    stderr: Path,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    own_group: bool = True,
    on_tick: Callable[[], None] | None = None,
    stdin: Path | None = None,
) -> int:
    with ExitStack() as stack:
        out = stack.enter_context(stdout.open("wb"))
        err = stack.enter_context(stderr.open("wb"))
        source = stack.enter_context(stdin.open("rb")) if stdin is not None else None
        stdout.chmod(0o600)
        stderr.chmod(0o600)
        with subprocess.Popen(
            command,
            stdin=source,
            stdout=out,
            stderr=err,
            cwd=cwd,
            env=env,
            start_new_session=own_group,
        ) as process:
            try:
                while True:
                    if on_tick is not None:
                        on_tick()
                    try:
                        code = process.wait(timeout=0.25 if on_tick else None)
                    except subprocess.TimeoutExpired:
                        continue
                    if on_tick is not None:
                        on_tick()
                    return code
            finally:
                if own_group:
                    stop_group(process.pid)
                elif process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                process.wait()


def stop_abandoned(run_id: str) -> None:
    token = f"RPG_LIBRARIAN_BATCH_RUN_ID={run_id}".encode()
    groups: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if token in (entry / "environ").read_bytes().split(b"\0"):
                group = os.getpgid(int(entry.name))
                if group != os.getpgrp():
                    groups.add(group)
        except (OSError, ProcessLookupError):
            continue
    for group in groups:
        stop_group(group)
