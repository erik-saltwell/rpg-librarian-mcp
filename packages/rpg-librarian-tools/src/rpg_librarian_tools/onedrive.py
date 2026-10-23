"""Read-only Graph operations with bounded retries and private download URLs."""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
TRANSIENT = {429, 500, 502, 503, 504}
ATTEMPTS = 5


class GraphError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"OneDrive request failed (HTTP {status}).")


class OneDrive:
    def __init__(
        self,
        token: str | Callable[[], str],
        drive: str,
        root: str,
        deadline: float,
        *,
        refresh_token: Callable[[], str] | None = None,
        diagnostic: Callable[[dict], None] | None = None,
    ):
        self.drive, self.root, self.deadline = drive, root, deadline
        self.token, self.refresh_token, self.diagnostic = (
            token,
            refresh_token,
            diagnostic,
        )
        self.http = requests.Session()
        if isinstance(token, str):
            self.http.headers["Authorization"] = f"Bearer {token}"

    def url(self, item: str, suffix: str = "") -> str:
        return (
            f"{GRAPH}/drives/{quote(self.drive, safe='')}/items/"
            f"{quote(item, safe='')}{suffix}"
        )

    def timeout(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("OneDrive time budget reached; progress saved.")
        return min(45.0, remaining)

    def emit(self, event: dict, response: requests.Response | None = None) -> None:
        if response is not None:
            event["status"] = response.status_code
            if event["operation"] != "content" and response.status_code >= 400:
                try:
                    code = response.json().get("error", {}).get("code")
                    if isinstance(code, str) and re.fullmatch(
                        r"[A-Za-z0-9_.-]{1,128}", code
                    ):
                        event["service_error_code"] = code
                except (ValueError, AttributeError, TypeError):
                    pass
            # Allowlist headers; never retain URLs, authorization or response bodies.
            for header in ("request-id", "client-request-id", "x-ms-request-id"):
                if value := response.headers.get(header):
                    event[header.replace("-", "_")] = "".join(
                        c for c in value[:256] if c.isprintable()
                    )
        if self.diagnostic:
            self.diagnostic(event)

    def retry(self, attempt: int, response: requests.Response | None) -> float:
        delay = 2**attempt + random.uniform(0, 1)
        if response is not None and (value := response.headers.get("Retry-After")):
            try:
                requested = float(value)
            except ValueError:
                try:
                    requested = (
                        parsedate_to_datetime(value) - datetime.now(UTC)
                    ).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    requested = 0
            if math.isfinite(requested) and requested > 0:
                delay = max(delay, requested)
        return delay

    def pause(self, delay: float) -> None:
        if time.monotonic() + delay >= self.deadline:
            raise TimeoutError("OneDrive retry exceeds the run budget; progress saved.")
        time.sleep(delay)

    def get(
        self,
        url: str,
        *,
        redirect: bool = True,
        operation: str = "page",
        item: str | None = None,
    ) -> requests.Response:
        if urlparse(url).hostname != "graph.microsoft.com":
            raise ValueError("Refusing an unexpected Graph pagination host.")
        refreshed = False
        attempt = 0
        while attempt < ATTEMPTS:
            response = None
            started = time.monotonic()
            event = {"operation": operation, "item_id": item, "attempt": attempt + 1}
            self.timeout()
            if not isinstance(self.token, str):
                self.http.headers["Authorization"] = f"Bearer {self.token()}"
            try:
                response = self.http.get(
                    url, timeout=self.timeout(), allow_redirects=False
                )
            except requests.RequestException:
                event["error_type"] = "ConnectionError"
            event["duration_ms"] = round((time.monotonic() - started) * 1000)
            if response is not None and response.status_code in (200, 302):
                self.emit({**event, "outcome": "completed"}, response)
                return response
            if (
                response is not None
                and response.status_code == 401
                and not refreshed
                and self.refresh_token is not None
            ):
                self.emit({**event, "outcome": "refresh_token"}, response)
                response.close()
                self.http.headers["Authorization"] = f"Bearer {self.refresh_token()}"
                refreshed = True
                continue
            retryable = response is None or response.status_code in TRANSIENT
            delay = self.retry(attempt, response) if retryable else 0
            retrying = retryable and attempt + 1 < ATTEMPTS
            self.emit(
                {
                    **event,
                    "outcome": "retry" if retrying else "failed",
                    "retry_delay_seconds": delay if retrying else 0,
                },
                response,
            )
            status = response.status_code if response is not None else None
            if response is not None:
                response.close()
            if not retrying:
                if status is not None:
                    raise GraphError(status)
                raise ConnectionError("OneDrive connection failed after retries.")
            self.pause(delay)
            attempt += 1
        raise RuntimeError("OneDrive retry exhausted.")

    def metadata(self, item: str) -> dict:
        with self.get(self.url(item), operation="metadata", item=item) as response:
            return response.json()

    def page(self, url: str) -> dict:
        with self.get(url) as response:
            return response.json()

    def delta_url(self) -> str:
        return self.url(self.root, "/delta?$top=1000")

    def download(self, item: str, destination: Path, expected_size: int) -> str:
        for attempt in range(ATTEMPTS):
            # Retry the entire transfer with a fresh short-lived download URL.
            with self.get(
                self.url(item, "/content"), operation="content_location", item=item
            ) as response:
                location = response.headers.get("Location")
                if (
                    response.status_code != 302
                    or not location
                    or urlparse(location).scheme != "https"
                ):
                    raise RuntimeError(
                        "OneDrive did not return a secure download location."
                    )
            digest, received = hashlib.sha256(), 0
            started = time.monotonic()
            event = {
                "operation": "content",
                "item_id": item,
                "attempt": attempt + 1,
                "expected_bytes": expected_size,
            }
            stream = None
            failure = None
            retryable = True
            delay = 0
            completed = False
            try:
                # Never forward the Graph bearer token to the storage host.
                stream = requests.get(location, stream=True, timeout=self.timeout())
                event["host"] = urlparse(stream.url or location).hostname
                if stream.status_code != 200:
                    failure = GraphError(stream.status_code)
                    retryable = stream.status_code in TRANSIENT or (
                        stream.status_code in {401, 403} and attempt == 0
                    )
                else:
                    with destination.open("wb") as output:
                        for chunk in stream.iter_content(1024 * 1024):
                            self.timeout()
                            received += len(chunk)
                            if received > expected_size:
                                raise RuntimeError("Remote file grew during download.")
                            output.write(chunk)
                            digest.update(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if received == expected_size:
                        completed = True
                    else:
                        failure = ConnectionError("Incomplete OneDrive download.")
                delay = self.retry(attempt, stream)
            except requests.RequestException:
                failure = ConnectionError("OneDrive content transfer failed.")
                delay = self.retry(attempt, stream)
            finally:
                retrying = failure is not None and retryable and attempt + 1 < ATTEMPTS
                event.update(
                    received_bytes=received,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    outcome="completed"
                    if completed
                    else "retry"
                    if retrying
                    else "failed",
                    retry_delay_seconds=delay if retrying else 0,
                )
                if failure:
                    event["error_type"] = type(failure).__name__
                try:
                    self.emit(event, stream)
                finally:
                    if stream is not None:
                        stream.close()
                    if not completed:
                        destination.unlink(missing_ok=True)
            if completed:
                return digest.hexdigest()
            assert failure is not None
            if not retrying:
                raise failure
            self.pause(delay)
        raise RuntimeError("OneDrive transfer retry exhausted.")

    def close(self) -> None:
        self.http.close()
