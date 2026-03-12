"""JSON structured logging setup."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.core.request_context import get_correlation_id, get_request_id


class JsonFormatter(logging.Formatter):
    """Simple JSON formatter for operational logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "breeze-service"),
            "operation": getattr(record, "operation", None),
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
            "duration_ms": getattr(record, "duration_ms", None),
            "http_status": getattr(record, "http_status", None),
            "message": record.getMessage(),
        }
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger to emit JSON logs."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
