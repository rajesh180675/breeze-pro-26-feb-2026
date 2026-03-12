"""Compatibility shim for domain error types."""

from app.domain.errors import (
    AuthenticationError,
    BadRequestError,
    BreezeAPIError,
    CircuitOpenError,
    NotFoundError,
    RateLimitError,
    TransientBreezeError,
)

__all__ = [
    "AuthenticationError",
    "BadRequestError",
    "BreezeAPIError",
    "CircuitOpenError",
    "NotFoundError",
    "RateLimitError",
    "TransientBreezeError",
]
