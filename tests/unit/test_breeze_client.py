from unittest.mock import Mock

import pytest

from lib.breeze_client import BreezeClient
from lib.errors import BadRequestError, RateLimitError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BREEZE_SESSION_TOKEN", "token")
    monkeypatch.setenv("BREEZE_CLIENT_ID", "id")
    monkeypatch.setenv("BREEZE_CLIENT_SECRET", "secret")
    return BreezeClient(base_url="https://example.com")


def _response(status: int, payload: dict | None = None):
    resp = Mock()
    resp.status_code = status
    resp.headers = {}
    resp.content = b"{}"
    resp.json.return_value = payload or {}
    if status >= 400:
        resp.raise_for_status.side_effect = Exception("http")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_request_success(client):
    client.session.request = Mock(return_value=_response(200, {"ok": True}))
    data = client.request("GET", "/positions")
    assert data["ok"] is True


def test_rate_limit_mapping(client):
    client.session.request = Mock(return_value=_response(429))
    with pytest.raises(RateLimitError):
        client.request("GET", "/positions")


def test_bad_request_mapping(client):
    client.session.request = Mock(return_value=_response(400))
    with pytest.raises(BadRequestError):
        client.request("POST", "/orders", json={"x": 1})
