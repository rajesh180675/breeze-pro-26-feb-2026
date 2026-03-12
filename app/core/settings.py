"""Typed settings for Breeze service runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse


class SettingsValidationError(ValueError):
    """Raised when runtime configuration is malformed."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Invalid settings: " + "; ".join(errors))


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return int(val)
    except ValueError as exc:
        raise SettingsValidationError([f"{name} must be an integer"]) from exc


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return float(val)
    except ValueError as exc:
        raise SettingsValidationError([f"{name} must be a float"]) from exc


@dataclass(frozen=True)
class Settings:
    service_name: str = "breeze-service"
    app_env: str = "dev"
    breeze_client_id: str | None = None
    breeze_client_secret: str | None = None
    breeze_session_token: str | None = None
    breeze_base_url: str = "https://api.icicidirect.com/breezeapi/api/v1"
    request_timeout_seconds: int = 15
    max_requests_per_minute: int = 100
    max_requests_per_day: int = 5000
    retry_total: int = 5
    retry_backoff_factor: float = 0.5
    circuit_failures_threshold: int = 5
    circuit_window_seconds: int = 60
    circuit_open_seconds: int = 45
    token_cache_file: str | None = None
    websocket_max_subscriptions: int = 2000
    sqlite_db_path: str = "data/breeze_trader.db"
    app_version: str = "0.1.0"
    app_build: str | None = None
    app_commit: str | None = None


def validate_settings(settings: Settings | None = None) -> Settings:
    """Validate runtime configuration invariants required at startup."""

    current = settings or get_settings()
    errors: list[str] = []

    positive_int_fields = {
        "request_timeout_seconds": current.request_timeout_seconds,
        "max_requests_per_minute": current.max_requests_per_minute,
        "max_requests_per_day": current.max_requests_per_day,
        "circuit_failures_threshold": current.circuit_failures_threshold,
        "circuit_window_seconds": current.circuit_window_seconds,
        "circuit_open_seconds": current.circuit_open_seconds,
        "websocket_max_subscriptions": current.websocket_max_subscriptions,
    }
    for field_name, value in positive_int_fields.items():
        if value <= 0:
            errors.append(f"{field_name} must be greater than 0")

    if current.retry_total < 0:
        errors.append("retry_total must be 0 or greater")
    if current.retry_backoff_factor < 0:
        errors.append("retry_backoff_factor must be 0 or greater")
    if not current.sqlite_db_path.strip():
        errors.append("sqlite_db_path must not be blank")

    parsed_base_url = urlparse(current.breeze_base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        errors.append("breeze_base_url must be a valid http or https URL")

    if errors:
        raise SettingsValidationError(errors)
    return current


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object built from env vars."""

    return Settings(
        service_name=os.getenv("SERVICE_NAME", "breeze-service"),
        app_env=os.getenv("APP_ENV", "dev"),
        breeze_client_id=os.getenv("BREEZE_CLIENT_ID"),
        breeze_client_secret=os.getenv("BREEZE_CLIENT_SECRET"),
        breeze_session_token=os.getenv("BREEZE_SESSION_TOKEN"),
        breeze_base_url=os.getenv("BREEZE_BASE_URL", "https://api.icicidirect.com/breezeapi/api/v1"),
        request_timeout_seconds=_env_int("REQUEST_TIMEOUT_SECONDS", 15),
        max_requests_per_minute=_env_int("MAX_REQUESTS_PER_MINUTE", 100),
        max_requests_per_day=_env_int("MAX_REQUESTS_PER_DAY", 5000),
        retry_total=_env_int("RETRY_TOTAL", 5),
        retry_backoff_factor=_env_float("RETRY_BACKOFF_FACTOR", 0.5),
        circuit_failures_threshold=_env_int("CIRCUIT_FAILURES_THRESHOLD", 5),
        circuit_window_seconds=_env_int("CIRCUIT_WINDOW_SECONDS", 60),
        circuit_open_seconds=_env_int("CIRCUIT_OPEN_SECONDS", 45),
        token_cache_file=os.getenv("TOKEN_CACHE_FILE"),
        websocket_max_subscriptions=_env_int("WEBSOCKET_MAX_SUBSCRIPTIONS", 2000),
        sqlite_db_path=os.getenv("SQLITE_DB_PATH", "data/breeze_trader.db"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        app_build=os.getenv("APP_BUILD"),
        app_commit=os.getenv("APP_COMMIT"),
    )
