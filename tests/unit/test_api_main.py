import sqlite3

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.api.main import _readiness_status, app, create_app, healthz, ready, version
from app.lib.config import SettingsValidationError, get_settings, validate_settings


def _set_required_env(monkeypatch):
    monkeypatch.setenv("BREEZE_CLIENT_ID", "id")
    monkeypatch.setenv("BREEZE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BREEZE_SESSION_TOKEN", "token")


def test_healthz_ok():
    assert healthz() == {"status": "ok"}


def test_create_app_exposes_system_routes():
    get_settings.cache_clear()
    created = create_app()
    client = TestClient(created)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_module_level_app_uses_factory():
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200


def test_version_happy_path(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "breeze-service")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("APP_BUILD", "build-42")
    monkeypatch.setenv("APP_COMMIT", "abc123")
    get_settings.cache_clear()

    assert version() == {
        "service": "breeze-service",
        "version": "1.2.3",
        "build": "build-42",
        "commit": "abc123",
        "env": "test",
    }


def test_validate_settings_accepts_defaults():
    get_settings.cache_clear()
    assert validate_settings().service_name == "breeze-service"


def test_create_app_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()

    with pytest.raises(SettingsValidationError, match="request_timeout_seconds must be greater than 0"):
        create_app()


def test_create_app_rejects_invalid_base_url(monkeypatch):
    monkeypatch.setenv("BREEZE_BASE_URL", "ftp://example.com")
    get_settings.cache_clear()

    with pytest.raises(SettingsValidationError, match="breeze_base_url must be a valid http or https URL"):
        create_app()


def test_get_settings_rejects_non_numeric_env(monkeypatch):
    monkeypatch.setenv("MAX_REQUESTS_PER_MINUTE", "not-a-number")
    get_settings.cache_clear()

    with pytest.raises(SettingsValidationError, match="MAX_REQUESTS_PER_MINUTE must be an integer"):
        get_settings()


def test_ready_returns_503_when_required_env_missing(monkeypatch):
    monkeypatch.delenv("BREEZE_CLIENT_ID", raising=False)
    monkeypatch.delenv("BREEZE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("BREEZE_SESSION_TOKEN", raising=False)
    get_settings.cache_clear()

    ok, payload = _readiness_status()
    assert ok is False
    assert payload["ready"] is False
    assert payload["db_ready"] is False
    assert payload["reason"] == "missing_env"
    assert sorted(payload["missing_env"]) == [
        "BREEZE_CLIENT_ID",
        "BREEZE_CLIENT_SECRET",
        "BREEZE_SESSION_TOKEN",
    ]

    try:
        ready()
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail["reason"] == "missing_env"


def test_ready_returns_503_when_db_unavailable(monkeypatch, tmp_path):
    _set_required_env(monkeypatch)
    missing_dir = tmp_path / "missing" / "dir"
    monkeypatch.setenv("SQLITE_DB_PATH", str(missing_dir / "service.db"))
    get_settings.cache_clear()

    ok, payload = _readiness_status()
    assert ok is False
    assert payload["ready"] is False
    assert payload["db_ready"] is False
    assert payload["reason"] == "db_unavailable"
    assert payload["db_error"]

    try:
        ready()
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail["reason"] == "db_unavailable"


def test_ready_ok_when_required_env_present_and_db_reachable(monkeypatch, tmp_path):
    _set_required_env(monkeypatch)
    db_file = tmp_path / "ready.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("SELECT 1")
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    get_settings.cache_clear()

    ok, payload = _readiness_status()
    assert ok is True
    assert payload["ready"] is True
    assert payload["db_ready"] is True
    assert payload["db_path"] == str(db_file)

    assert ready() == payload
