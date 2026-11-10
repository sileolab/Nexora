"""Exceptions for Nexora Python SDK."""

from __future__ import annotations

from typing import Any, Optional


class NexoraError(Exception):
    """Base exception for all Nexora SDK errors."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NexoraAPIError(NexoraError):
    """Exception raised when the Nexora API returns an HTTP error code."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        data: Optional[Any] = None,
    ):
        super().__init__(f"API Error ({status_code}): {message}")
        self.status_code = status_code
        self.raw_message = message
        self.data = data


class NexoraAuthenticationError(NexoraAPIError):
    """Exception raised for HTTP 401 Unauthorized responses."""

    def __init__(self, message: str = "Invalid or missing API key.", data: Optional[Any] = None):
        super().__init__(message=message, status_code=401, data=data)


class NexoraNotFoundError(NexoraAPIError):
    """Exception raised for HTTP 404 Not Found responses."""

    def __init__(self, message: str = "Resource not found.", data: Optional[Any] = None):
        super().__init__(message=message, status_code=404, data=data)


class NexoraTimeoutError(NexoraError):
    """Exception raised when an operation or job polling exceeds its timeout threshold."""

    def __init__(self, message: str = "Operation timed out.", job_id: Optional[str] = None):
        super().__init__(message)
        self.job_id = job_id


# Backward compatibility aliases
CrawlbotError = NexoraError
CrawlbotAPIError = NexoraAPIError
CrawlbotAuthenticationError = NexoraAuthenticationError
CrawlbotNotFoundError = NexoraNotFoundError
CrawlbotTimeoutError = NexoraTimeoutError

__all__ = [
    "NexoraError",
    "NexoraAPIError",
    "NexoraAuthenticationError",
    "NexoraNotFoundError",
    "NexoraTimeoutError",
    "CrawlbotError",
    "CrawlbotAPIError",
    "CrawlbotAuthenticationError",
    "CrawlbotNotFoundError",
    "CrawlbotTimeoutError",
]
