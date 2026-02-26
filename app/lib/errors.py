"""Domain specific exceptions for Breeze integrations."""

from __future__ import annotations


class BreezeAPIError(Exception):
    """Base Breeze API error with HTTP and request context."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        http_status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.http_status = http_status
        self.request_id = request_id


class RateLimitError(BreezeAPIError):
    """Raised when a REST request exceeds Breeze quota constraints."""


class AuthenticationError(BreezeAPIError):
    """Raised when authentication/session setup fails."""


class BadRequestError(BreezeAPIError):
    """Raised for invalid request payloads (HTTP 400)."""


class NotFoundError(BreezeAPIError):
    """Raised when an endpoint or resource is missing (HTTP 404)."""


class TransientBreezeError(BreezeAPIError):
    """Raised for transient failures that may succeed on retry."""


class CircuitOpenError(BreezeAPIError):
    """Raised when the circuit breaker is open and requests are blocked."""
