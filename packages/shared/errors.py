"""Custom exceptions for teemeto shared package."""

from typing import Any


class TeemetoError(Exception):
    """Base exception for all teemeto errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TenantContextError(TeemetoError):
    """Raised when tenant_id is missing, invalid, or violates isolation rules."""

    pass


class RLSViolationError(TeemetoError):
    """Raised when an operation violates database Row Level Security policies."""

    pass


class RepositoryError(TeemetoError):
    """Raised when database repository operations fail."""

    pass
