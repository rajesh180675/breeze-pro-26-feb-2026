"""Compatibility shim for Breeze REST client surface."""

from app.infrastructure.breeze.rest_client import (
    ALERT_COUNTER,
    CACHE_HIT_RATE,
    CIRCUIT_FAILURES,
    CIRCUIT_STATE,
    INFLIGHT,
    ORDER_COUNTER,
    PNL_GAUGE,
    POSITION_GAUGE,
    REQUEST_COUNTER,
    REQUEST_LATENCY,
    WEBSOCKET_SUBS,
    BreezeClient,
    CircuitBreaker,
    CircuitBreakerState,
    SlidingWindowRateLimiter,
)

__all__ = [
    "ALERT_COUNTER",
    "CACHE_HIT_RATE",
    "CIRCUIT_FAILURES",
    "CIRCUIT_STATE",
    "INFLIGHT",
    "ORDER_COUNTER",
    "PNL_GAUGE",
    "POSITION_GAUGE",
    "REQUEST_COUNTER",
    "REQUEST_LATENCY",
    "WEBSOCKET_SUBS",
    "BreezeClient",
    "CircuitBreaker",
    "CircuitBreakerState",
    "SlidingWindowRateLimiter",
]
