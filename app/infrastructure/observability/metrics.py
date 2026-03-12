"""Prometheus metrics registry helpers used across the service."""

from __future__ import annotations

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
except ImportError:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain"

    class _Metric:
        def labels(self, **_kwargs):
            return self

        def inc(self):
            return None

        def dec(self):
            return None

        def observe(self, _value):
            return None

        def set(self, _value):
            return None

    def Counter(*_args, **_kwargs):  # type: ignore[no-redef]
        return _Metric()

    def Gauge(*_args, **_kwargs):  # type: ignore[no-redef]
        return _Metric()

    def Histogram(*_args, **_kwargs):  # type: ignore[no-redef]
        return _Metric()

    def generate_latest():
        return b""


REQUEST_COUNTER = Counter("breeze_requests_total", "Breeze requests", ["method", "endpoint", "result"])
REQUEST_LATENCY = Histogram("breeze_request_duration_seconds", "Breeze request duration", ["method", "endpoint"])
INFLIGHT = Gauge("breeze_client_inflight_requests", "Inflight Breeze requests")
CIRCUIT_STATE = Gauge("breeze_circuit_state", "Circuit state by endpoint", ["endpoint"])
CIRCUIT_FAILURES = Gauge("breeze_circuit_failures", "Circuit failures by endpoint", ["endpoint"])
ORDER_COUNTER = Counter("breeze_orders_total", "Orders placed", ["action", "instrument", "status"])
POSITION_GAUGE = Gauge("breeze_open_positions", "Open positions count")
PNL_GAUGE = Gauge("breeze_unrealized_pnl_inr", "Unrealized P&L in INR")
WEBSOCKET_SUBS = Gauge("breeze_ws_subscriptions", "Active WS subscriptions")
ALERT_COUNTER = Counter("breeze_alerts_dispatched_total", "Alerts sent", ["channel", "level"])
CACHE_HIT_RATE = Gauge("breeze_cache_hit_rate", "Cache hit rate by namespace", ["namespace"])


def render_metrics() -> str:
    """Serialize Prometheus metrics for the HTTP endpoint."""

    return generate_latest().decode("utf-8")
