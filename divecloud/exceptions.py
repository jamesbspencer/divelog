"""Custom exceptions for DiveCloud automation client."""

from typing import Optional


class DiveCloudError(Exception):
    """Base exception for all DiveCloud operations."""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class DiveCloudAuthError(DiveCloudError):
    """Raised when authentication fails (invalid credentials, unverified account, expired session)."""
    pass


class DiveCloudTimeoutError(DiveCloudError):
    """Raised when a DiveCloud network request times out due to server latency."""
    pass


class DiveCloudNetworkError(DiveCloudError):
    """Raised when connection issues or transient HTTP errors occur."""
    pass


class DiveCloudParseError(DiveCloudError):
    """Raised when DiveCloud response format cannot be parsed."""
    pass
