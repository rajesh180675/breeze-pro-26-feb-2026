"""HTTP middleware for request correlation and access logging."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.request_context import (
    clear_correlation_id,
    clear_request_id,
    set_correlation_id,
    set_request_id,
)

LOGGER = logging.getLogger(__name__)
REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach request correlation metadata to each HTTP request."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id

        set_request_id(request_id)
        set_correlation_id(correlation_id)
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            LOGGER.exception(
                "request_failed",
                extra={
                    "operation": request.url.path,
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "duration_ms": duration_ms,
                    "http_status": 500,
                    "method": request.method,
                },
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            LOGGER.info(
                "request_completed",
                extra={
                    "operation": request.url.path,
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "duration_ms": duration_ms,
                    "http_status": response.status_code,
                    "method": request.method,
                },
            )
            return response
        finally:
            clear_request_id()
            clear_correlation_id()
