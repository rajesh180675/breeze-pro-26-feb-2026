"""Production-grade Breeze REST client."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import requests  # type: ignore[import-untyped]

try:
    from prometheus_client import Counter, Gauge, Histogram
except ImportError:  # pragma: no cover

    class _Metric:
        def labels(self, **kwargs):
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


from requests.adapters import HTTPAdapter  # type: ignore[import-untyped]
from urllib3.util.retry import Retry

from app.lib.auth import AuthManager, FileTokenStore, InMemoryTokenStore, TokenRecord, TokenStore
from app.lib.config import Settings, get_settings
from app.lib.errors import (
    AuthenticationError,
    BadRequestError,
    CircuitOpenError,
    NotFoundError,
    RateLimitError,
    TransientBreezeError,
)

_AlertEvent: Any = None
_AlertLevel: Any = None

try:
    from alerting import AlertEvent as _ImportedAlertEvent
    from alerting import AlertLevel as _ImportedAlertLevel

    _AlertEvent = _ImportedAlertEvent
    _AlertLevel = _ImportedAlertLevel
except ImportError:  # pragma: no cover
    logging.getLogger(__name__).debug("alerting_module_not_available")

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

LOGGER = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """Simple global minute/day limiter for REST API calls."""

    def __init__(self, max_per_minute: int, max_per_day: int) -> None:
        self.max_per_minute = max_per_minute
        self.max_per_day = max_per_day
        self._minute_events: deque[float] = deque()
        self._day_events: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self) -> None:
        now = time.time()
        with self._lock:
            while self._minute_events and now - self._minute_events[0] > 60:
                self._minute_events.popleft()
            while self._day_events and now - self._day_events[0] > 86400:
                self._day_events.popleft()
            if len(self._minute_events) >= self.max_per_minute:
                raise RateLimitError("Exceeded minute quota", operation="request", http_status=429)
            if len(self._day_events) >= self.max_per_day:
                raise RateLimitError("Exceeded daily quota", operation="request", http_status=429)
            self._minute_events.append(now)
            self._day_events.append(now)


class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Endpoint-aware circuit breaker with half-open health probe."""

    def __init__(self, threshold: int, window_seconds: int, open_seconds: int, alert_dispatcher: Any = None) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.base_open_seconds = open_seconds
        self._alert_dispatcher = alert_dispatcher
        self._errors: dict[str, deque[float]] = defaultdict(deque)
        self._state: dict[str, CircuitBreakerState] = defaultdict(lambda: CircuitBreakerState.CLOSED)
        self._opened_at: dict[str, float | None] = defaultdict(lambda: None)
        self._recovery_timeout: dict[str, int] = defaultdict(lambda: self.base_open_seconds)

    def _emit_metrics(self, endpoint: str) -> None:
        state = self._state[endpoint]
        state_value = 0 if state == CircuitBreakerState.CLOSED else 1 if state == CircuitBreakerState.OPEN else 2
        CIRCUIT_STATE.labels(endpoint=endpoint).set(state_value)
        CIRCUIT_FAILURES.labels(endpoint=endpoint).set(len(self._errors[endpoint]))

    def _notify_open(self, endpoint: str) -> None:
        if self._alert_dispatcher is None or _AlertEvent is None or _AlertLevel is None:
            return
        event = _AlertEvent(
            alert_type="api_circuit_open",
            level=_AlertLevel.CRITICAL,
            title="API Circuit Open",
            body=f"Circuit opened for endpoint {endpoint}",
            metadata={"endpoint": endpoint},
        )
        self._alert_dispatcher.dispatch(event)

    def before_request(self, endpoint: str) -> bool:
        now = time.time()
        state = self._state[endpoint]
        opened_at = self._opened_at[endpoint]
        if state == CircuitBreakerState.OPEN:
            if opened_at and (now - opened_at) >= self._recovery_timeout[endpoint]:
                self._state[endpoint] = CircuitBreakerState.HALF_OPEN
                self._emit_metrics(endpoint)
                return True
            raise CircuitOpenError("Circuit breaker open", operation=endpoint)
        self._emit_metrics(endpoint)
        return state == CircuitBreakerState.HALF_OPEN

    def record_success(self, endpoint: str) -> None:
        self._errors[endpoint].clear()
        self._state[endpoint] = CircuitBreakerState.CLOSED
        self._opened_at[endpoint] = None
        self._recovery_timeout[endpoint] = self.base_open_seconds
        self._emit_metrics(endpoint)

    def record_failure(self, endpoint: str) -> None:
        now = time.time()
        errors = self._errors[endpoint]
        errors.append(now)
        while errors and now - errors[0] > self.window_seconds:
            errors.popleft()
        if self._state[endpoint] == CircuitBreakerState.HALF_OPEN:
            self._state[endpoint] = CircuitBreakerState.OPEN
            self._opened_at[endpoint] = now
            self._recovery_timeout[endpoint] = max(self.base_open_seconds, self._recovery_timeout[endpoint] * 2)
            self._notify_open(endpoint)
        elif len(errors) >= self.threshold:
            self._state[endpoint] = CircuitBreakerState.OPEN
            self._opened_at[endpoint] = now
            self._notify_open(endpoint)
        self._emit_metrics(endpoint)


class BreezeClient:
    """Breeze REST wrapper with auth, retries, and quotas."""

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str | None = None,
        session_store: TokenStore | None = None,
    ) -> None:
        self.settings: Settings = get_settings()
        self.client_id = client_id or self.settings.breeze_client_id
        self.client_secret = client_secret or self.settings.breeze_client_secret
        self.base_url = (base_url or self.settings.breeze_base_url).rstrip("/")

        if session_store:
            store = session_store
        elif self.settings.token_cache_file:
            store = FileTokenStore(self.settings.token_cache_file)
        else:
            store = InMemoryTokenStore()

        self.auth_manager = AuthManager(token_store=store)
        self.rate_limiter = SlidingWindowRateLimiter(
            max_per_minute=self.settings.max_requests_per_minute,
            max_per_day=self.settings.max_requests_per_day,
        )
        self.circuit = CircuitBreaker(
            threshold=self.settings.circuit_failures_threshold,
            window_seconds=self.settings.circuit_window_seconds,
            open_seconds=self.settings.circuit_open_seconds,
            alert_dispatcher=None,
        )

        self.session = requests.Session()
        retries = Retry(
            total=self.settings.retry_total,
            backoff_factor=self.settings.retry_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def authenticate(self) -> None:
        """Persist a Breeze session token from env-driven auth flow."""
        token = self.settings.breeze_session_token
        self.auth_manager.authenticate(session_token=token)

    def ensure_authenticated(self) -> None:
        """Ensure session token is available and refreshed before expiry."""

        def _refresh() -> TokenRecord:
            token = self.settings.breeze_session_token
            if not token:
                raise AuthenticationError("Unable to refresh token", operation="ensure_authenticated")
            now = datetime.now(tz=timezone.utc)
            return TokenRecord(access_token=token, issued_at=now, expires_at=now + timedelta(hours=24))

        self.auth_manager.ensure_fresh_token(_refresh)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Execute a Breeze request with auth, quotas, retries and mapped errors."""
        endpoint = f"/{path.lstrip('/')}"
        half_open_probe = self.circuit.before_request(endpoint)
        self.rate_limiter.check()
        self.ensure_authenticated()
        record = self.auth_manager.current()
        if not record:
            raise AuthenticationError("No auth token loaded", operation=path)

        if half_open_probe:
            probe_url = f"{self.base_url}/customerdetails"
            probe_headers = {
                "X-SessionToken": record.access_token,
                "X-AppKey": self.client_id or "",
            }
            probe_resp = self.session.get(
                probe_url,
                headers=probe_headers,
                timeout=self.settings.request_timeout_seconds,
            )
            if probe_resp.status_code >= 400:
                self.circuit.record_failure(endpoint)
                raise CircuitOpenError("Circuit breaker probe failed", operation=endpoint)
            self.circuit.record_success(endpoint)

        request_headers = {
            "X-SessionToken": record.access_token,
            "X-AppKey": self.client_id or "",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key

        url = f"{self.base_url}/{path.lstrip('/')}"
        started = time.perf_counter()
        INFLIGHT.inc()
        try:
            resp = self.session.request(
                method,
                url,
                params=params,
                json=json,
                headers=request_headers,
                timeout=self.settings.request_timeout_seconds,
            )
            duration = time.perf_counter() - started
            REQUEST_LATENCY.labels(method=method.upper(), endpoint=endpoint).observe(duration)
            request_id = resp.headers.get("X-Request-ID")
            if resp.status_code >= 500:
                self.circuit.record_failure(endpoint)
                REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="5xx").inc()
                raise TransientBreezeError(
                    "Transient server error",
                    operation=path,
                    http_status=resp.status_code,
                    request_id=request_id,
                )
            if resp.status_code == 429:
                REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="rate_limited").inc()
                raise RateLimitError("Breeze rate limit hit", operation=path, http_status=429, request_id=request_id)
            if resp.status_code == 401:
                self.authenticate()
                REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="auth_error").inc()
                raise AuthenticationError("Unauthorized", operation=path, http_status=401, request_id=request_id)
            if resp.status_code == 400:
                REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="bad_request").inc()
                raise BadRequestError("Bad request", operation=path, http_status=400, request_id=request_id)
            if resp.status_code == 404:
                REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="not_found").inc()
                raise NotFoundError("Resource not found", operation=path, http_status=404, request_id=request_id)
            resp.raise_for_status()
            self.circuit.record_success(endpoint)
            REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="ok").inc()
            return resp.json() if resp.content else {}
        except requests.RequestException as exc:
            self.circuit.record_failure(endpoint)
            REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="transport_error").inc()
            raise TransientBreezeError(str(exc), operation=path) from exc
        finally:
            INFLIGHT.dec()
            LOGGER.info("breeze_request_complete", extra={"operation": path})

    def _idempotency(self) -> str:
        return str(uuid.uuid4())

    def get_customer_details(self) -> dict:
        """Fetch customer profile details (health probe endpoint)."""
        return self.request("GET", "/customerdetails")

    def get_instruments(self, exchange: str | None = None) -> dict:
        """Fetch instruments.

        Example:
            client.get_instruments(exchange="NSE")
        """
        return self.request("GET", "/instruments", params={"exchange": exchange} if exchange else None)

    def get_security_master(self) -> dict:
        """Fetch security master metadata."""
        return self.request("GET", "/securitymaster")

    def get_historical(self, symbol: str, from_ts: str, to_ts: str, interval: str) -> dict:
        """Fetch historical candles for a symbol."""
        return self.request(
            "GET",
            "/historicalcharts",
            params={"symbol": symbol, "from": from_ts, "to": to_ts, "interval": interval},
        )

    def get_option_chain(self, symbol: str) -> dict:
        """Fetch option chain data."""
        return self.request("GET", "/optionchain", params={"symbol": symbol})

    def place_order(self, order_payload: dict) -> dict:
        """Place an order with idempotency key support."""
        action = str(order_payload.get("action", "unknown")).lower()
        instrument = str(order_payload.get("stock_code", order_payload.get("symbol", "unknown"))).upper()
        try:
            resp = self.request("POST", "/orders", json=order_payload, idempotency_key=self._idempotency())
            ORDER_COUNTER.labels(action=action, instrument=instrument, status="success").inc()
            return resp
        except Exception:
            ORDER_COUNTER.labels(action=action, instrument=instrument, status="failed").inc()
            raise

    def modify_order(self, order_id: str, updates: dict) -> dict:
        """Modify an existing order."""
        return self.request("PUT", f"/orders/{order_id}", json=updates)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an order."""
        return self.request("DELETE", f"/orders/{order_id}")

    def get_positions(self) -> dict:
        """Fetch current positions."""
        resp = self.request("GET", "/positions")
        rows = resp.get("Success") if isinstance(resp, dict) else []
        if rows is None and isinstance(resp, dict):
            rows = resp.get("data", [])
        rows = rows if isinstance(rows, list) else []
        POSITION_GAUGE.set(len(rows))
        pnl = 0.0
        for row in rows:
            try:
                pnl += float(row.get("pnl", 0) or 0)
            except (TypeError, ValueError, AttributeError) as exc:
                LOGGER.warning("invalid_position_pnl_row", extra={"error": str(exc)})
                continue
        PNL_GAUGE.set(pnl)
        return resp

    def get_order_status(self, order_id: str) -> dict:
        """Fetch status for one order."""
        return self.request("GET", f"/orders/{order_id}")

    def download_security_master_file(self, path: str) -> bytes:
        """Download security master binary file.

        Expected response shape: bytes blob, see Breeze docs.
        """
        self.ensure_authenticated()
        record = self.auth_manager.current()
        if not record:
            raise AuthenticationError("No auth token loaded", operation=path)
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = self.session.get(
            url,
            headers={"X-SessionToken": record.access_token, "X-AppKey": self.client_id or ""},
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.content
