"""Production-grade Breeze REST client."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import requests
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
    def Counter(*_args, **_kwargs):
        return _Metric()
    def Gauge(*_args, **_kwargs):
        return _Metric()
    def Histogram(*_args, **_kwargs):
        return _Metric()
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from lib.auth import AuthManager, FileTokenStore, InMemoryTokenStore, TokenRecord, TokenStore
from lib.config import Settings, get_settings
from lib.errors import (
    AuthenticationError,
    BadRequestError,
    BreezeAPIError,
    CircuitOpenError,
    NotFoundError,
    RateLimitError,
    TransientBreezeError,
)

REQUEST_COUNTER = Counter("breeze_requests_total", "Breeze requests", ["method", "endpoint", "result"])
REQUEST_LATENCY = Histogram("breeze_request_duration_seconds", "Breeze request duration", ["method", "endpoint"])
INFLIGHT = Gauge("breeze_client_inflight_requests", "Inflight Breeze requests")

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


class CircuitBreaker:
    """Consecutive transient-failure circuit breaker."""

    def __init__(self, threshold: int, window_seconds: int, open_seconds: int) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.open_seconds = open_seconds
        self._errors: deque[float] = deque()
        self._opened_at: float | None = None

    def before_request(self) -> None:
        if self._opened_at and (time.time() - self._opened_at) < self.open_seconds:
            raise CircuitOpenError("Circuit breaker open", operation="request")
        if self._opened_at and (time.time() - self._opened_at) >= self.open_seconds:
            self._opened_at = None
            self._errors.clear()

    def record_success(self) -> None:
        self._errors.clear()

    def record_failure(self) -> None:
        now = time.time()
        self._errors.append(now)
        while self._errors and now - self._errors[0] > self.window_seconds:
            self._errors.popleft()
        if len(self._errors) >= self.threshold:
            self._opened_at = now


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
            return TokenRecord(access_token=token, expires_at=datetime.now(tz=timezone.utc).replace(hour=23, minute=59))

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
        self.circuit.before_request()
        self.rate_limiter.check()
        self.ensure_authenticated()
        record = self.auth_manager.current()
        if not record:
            raise AuthenticationError("No auth token loaded", operation=path)

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
        endpoint = f"/{path.lstrip('/')}"
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
                self.circuit.record_failure()
                REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="5xx").inc()
                raise TransientBreezeError("Transient server error", operation=path, http_status=resp.status_code, request_id=request_id)
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
            self.circuit.record_success()
            REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="ok").inc()
            return resp.json() if resp.content else {}
        except requests.RequestException as exc:
            self.circuit.record_failure()
            REQUEST_COUNTER.labels(method=method.upper(), endpoint=endpoint, result="transport_error").inc()
            raise TransientBreezeError(str(exc), operation=path) from exc
        finally:
            INFLIGHT.dec()
            LOGGER.info("breeze_request_complete", extra={"operation": path})

    def _idempotency(self) -> str:
        return str(uuid.uuid4())

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
        return self.request("GET", "/historicalcharts", params={"symbol": symbol, "from": from_ts, "to": to_ts, "interval": interval})

    def get_option_chain(self, symbol: str) -> dict:
        """Fetch option chain data."""
        return self.request("GET", "/optionchain", params={"symbol": symbol})

    def place_order(self, order_payload: dict) -> dict:
        """Place an order with idempotency key support."""
        return self.request("POST", "/orders", json=order_payload, idempotency_key=self._idempotency())

    def modify_order(self, order_id: str, updates: dict) -> dict:
        """Modify an existing order."""
        return self.request("PUT", f"/orders/{order_id}", json=updates)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an order."""
        return self.request("DELETE", f"/orders/{order_id}")

    def get_positions(self) -> dict:
        """Fetch current positions."""
        return self.request("GET", "/positions")

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
