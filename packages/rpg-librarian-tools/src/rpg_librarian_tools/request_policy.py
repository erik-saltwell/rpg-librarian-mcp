from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestPolicy:
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    minimum_request_interval: float = 1.0
    max_concurrency: int = 5

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        if self.minimum_request_interval < 0:
            raise ValueError("minimum_request_interval cannot be negative")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")


DEFAULT_REQUEST_POLICY = RequestPolicy()
