import os
import time

import pytest

from rpg_librarian_mcp.tools.isolated_worker import (
    IsolatedWorkerPool,
    SynchronousWorkerPool,
)


def _add(a: int, b: int) -> int:
    return a + b


def _raise_value_error() -> None:
    raise ValueError("bad input")


def _crash() -> None:
    os._exit(1)  # simulates a segfault/OOM-kill -- no chance to raise cleanly


def _sleep(seconds: float) -> str:
    time.sleep(seconds)
    return "done"


def test_synchronous_pool_runs_in_process_and_returns_result():
    pool = SynchronousWorkerPool()

    assert pool.submit(_add, 2, 3) == 5


def test_synchronous_pool_propagates_exceptions():
    pool = SynchronousWorkerPool()

    with pytest.raises(ValueError, match="bad input"):
        pool.submit(_raise_value_error)


def test_isolated_pool_runs_function_in_subprocess_and_returns_result():
    pool = IsolatedWorkerPool(timeout_s=10)
    try:
        assert pool.submit(_add, 2, 3) == 5
    finally:
        pool.close()


def test_isolated_pool_propagates_exceptions_raised_inside_the_function():
    pool = IsolatedWorkerPool(timeout_s=10)
    try:
        with pytest.raises(ValueError, match="bad input"):
            pool.submit(_raise_value_error)
    finally:
        pool.close()


def test_isolated_pool_survives_a_worker_crash_and_keeps_serving_later_calls():
    pool = IsolatedWorkerPool(timeout_s=10)
    try:
        with pytest.raises(RuntimeError, match="worker crashed"):
            pool.submit(_crash)

        # The pool -- not the crashed worker -- is still usable afterward:
        # pebble transparently replaced it.
        assert pool.submit(_add, 2, 3) == 5
    finally:
        pool.close()


def test_isolated_pool_kills_a_hung_task_past_its_timeout():
    pool = IsolatedWorkerPool(timeout_s=0.2)
    try:
        with pytest.raises(RuntimeError, match="exceeded"):
            pool.submit(_sleep, 5)

        assert pool.submit(_add, 2, 3) == 5
    finally:
        pool.close()
