from fastapi import HTTPException

from app.api.main import _readiness_status, healthz, ready
from app.lib.config import get_settings


def test_healthz_ok():
    assert healthz() == {"status": "ok"}


def test_ready_returns_503_when_required_env_missing(monkeypatch):
    monkeypatch.delenv("BREEZE_CLIENT_ID", raising=False)
    monkeypatch.delenv("BREEZE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("BREEZE_SESSION_TOKEN", raising=False)
    get_settings.cache_clear()

    ok, payload = _readiness_status()
    assert ok is False
    assert payload["ready"] is False
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


def test_ready_ok_when_required_env_present(monkeypatch):
    monkeypatch.setenv("BREEZE_CLIENT_ID", "id")
    monkeypatch.setenv("BREEZE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BREEZE_SESSION_TOKEN", "token")
    get_settings.cache_clear()

    ok, payload = _readiness_status()
    assert ok is True
    assert payload == {"ready": True}
    assert ready() == {"ready": True}
