from __future__ import annotations

from pathlib import Path


class ToolError(Exception):
    """Base class for stable, package-owned tool failures."""


class InvalidInputError(ToolError, ValueError):
    """A caller supplied an invalid argument."""


class DependencyUnavailableError(ToolError):
    """A required system dependency, such as Tesseract, is unavailable."""


class DocumentProcessingError(ToolError):
    """A document could not be processed completely."""

    def __init__(self, path: Path, operation: str, page: int | None = None) -> None:
        self.path = path
        self.operation = operation
        self.page = page
        super().__init__(path, operation, page)

    def __str__(self) -> str:
        location = f" page {self.page}" if self.page is not None else ""
        return f"{self.operation} failed for {self.path}{location}"


class AuthenticationError(ToolError):
    """A remote service rejected the supplied credentials."""


class RateLimitError(ToolError):
    """A remote service rate limit remained exhausted after retries."""

    def __init__(self, service: str, retry_after: float | None = None) -> None:
        self.service = service
        self.retry_after = retry_after
        super().__init__(service, retry_after)


class RemoteServiceError(ToolError):
    """A remote service request failed after applying its request policy."""

    def __init__(
        self,
        service: str,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.service = service
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(service, status_code, retryable)
