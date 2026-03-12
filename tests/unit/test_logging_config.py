import json
import logging

from app.core.request_context import clear_correlation_id, clear_request_id, set_correlation_id, set_request_id
from app.lib.logging_config import JsonFormatter, configure_logging


def test_json_formatter_includes_message_and_defaults():
    formatter = JsonFormatter()
    record = logging.makeLogRecord({"levelname": "INFO", "msg": "hello"})

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "hello"
    assert payload["service"] == "breeze-service"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload


def test_json_formatter_reads_extra_fields():
    formatter = JsonFormatter()
    record = logging.makeLogRecord(
        {
            "levelname": "WARNING",
            "msg": "slow call",
            "service": "svc",
            "operation": "fetch",
            "correlation_id": "corr-1",
            "request_id": "req-1",
            "duration_ms": 25,
            "http_status": 429,
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["service"] == "svc"
    assert payload["operation"] == "fetch"
    assert payload["correlation_id"] == "corr-1"
    assert payload["request_id"] == "req-1"
    assert payload["duration_ms"] == 25
    assert payload["http_status"] == 429


def test_configure_logging_sets_root_handler_and_level():
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    try:
        configure_logging(level=logging.DEBUG)

        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.DEBUG
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)


def test_json_formatter_reads_request_context_defaults():
    formatter = JsonFormatter()
    set_request_id("req-context")
    set_correlation_id("corr-context")
    try:
        record = logging.makeLogRecord({"levelname": "INFO", "msg": "context log"})
        payload = json.loads(formatter.format(record))
    finally:
        clear_request_id()
        clear_correlation_id()

    assert payload["request_id"] == "req-context"
    assert payload["correlation_id"] == "corr-context"
