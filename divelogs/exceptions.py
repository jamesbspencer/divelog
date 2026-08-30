"""Custom exceptions for Divelogs.org API client."""

from __future__ import annotations

from typing import Optional


class DivelogsError(Exception):
    """Base exception for Divelogs.org API interactions."""
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"(status: {self.status_code})")
        if self.details:
            parts.append(f"- details: {self.details}")
        return " ".join(parts)


class DivelogsAuthError(DivelogsError):
    """Raised when authentication fails (invalid credentials or expired bearer token)."""
    pass


class DivelogsUploadError(DivelogsError):
    """Raised when dive upload or payload validation fails."""
    pass
