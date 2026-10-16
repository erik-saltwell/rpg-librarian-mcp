"""Read-only Graph operations. Credentials and temporary download URLs stay private."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

GRAPH = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"OneDrive request failed (HTTP {status}).")


class OneDrive:
    def __init__(self, token: str, drive: str, root: str, deadline: float):
        self.drive, self.root, self.deadline = drive, root, deadline
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"

    def url(self, item: str, suffix: str = "") -> str:
        return (
            f"{GRAPH}/drives/{quote(self.drive, safe='')}/items/"
            f"{quote(item, safe='')}{suffix}"
        )

    def get(self, url: str, *, redirect: bool = True) -> requests.Response:
        if urlparse(url).hostname != "graph.microsoft.com":
            raise ValueError("Refusing an unexpected Graph pagination host.")
        for attempt in range(4):
            if time.monotonic() >= self.deadline:
                raise TimeoutError("OneDrive time budget reached; progress saved.")
            try:
                response = self.http.get(url, timeout=45, allow_redirects=False)
            except requests.RequestException:
                if attempt == 3:
                    raise ConnectionError("OneDrive connection failed.") from None
                response = None
            if response is not None:
                if response.status_code in (200, 302):
                    return response
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise GraphError(response.status_code)
            delay = 2**attempt
            if response is not None:
                try:
                    delay = max(delay, int(response.headers.get("Retry-After", "0")))
                except ValueError:
                    delay = max(delay, 5)
            if attempt == 3:
                raise GraphError(response.status_code if response is not None else 503)
            if time.monotonic() + delay >= self.deadline:
                raise TimeoutError("OneDrive retry exceeds the run budget.")
            time.sleep(delay)
        raise RuntimeError("OneDrive retry exhausted.")

    def metadata(self, item: str) -> dict:
        return self.get(self.url(item)).json()

    def page(self, url: str) -> dict:
        return self.get(url).json()

    def delta_url(self) -> str:
        return self.url(self.root, "/delta?$top=1000")

    def download(self, item: str, destination: Path, expected_size: int) -> str:
        response = self.get(self.url(item, "/content"))
        location = response.headers.get("Location")
        if (
            response.status_code != 302
            or not location
            or urlparse(location).scheme != "https"
        ):
            raise RuntimeError("OneDrive did not return a secure download location.")
        # Separate request: never forward the Graph bearer token to the storage host.
        digest, received = hashlib.sha256(), 0
        try:
            with requests.get(location, stream=True, timeout=45) as stream:
                if stream.status_code != 200:
                    raise GraphError(stream.status_code)
                with destination.open("wb") as output:
                    for chunk in stream.iter_content(1024 * 1024):
                        if time.monotonic() >= self.deadline:
                            raise TimeoutError("Download paused at the run deadline.")
                        received += len(chunk)
                        if received > expected_size:
                            raise RuntimeError("Remote file grew during download.")
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    import os

                    os.fsync(output.fileno())
        except requests.RequestException:
            raise ConnectionError("OneDrive content transfer failed.") from None
        if received != expected_size:
            raise RuntimeError("Incomplete OneDrive download; retry on the next run.")
        return digest.hexdigest()

    def close(self) -> None:
        self.http.close()
