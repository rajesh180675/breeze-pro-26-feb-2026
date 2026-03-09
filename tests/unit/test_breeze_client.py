from unittest.mock import Mock

import pytest
import requests

from lib.breeze_client import BreezeClient, CircuitBreakerState
from lib.errors import (
    AuthenticationError,
    BadRequestError,
    CircuitOpenError,
    NotFoundError,
    RateLimitError,
    TransientBreezeError,
)


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


def test_not_found_mapping(client):
    client.session.request = Mock(return_value=_response(404))
    with pytest.raises(NotFoundError):
        client.request("GET", "/orders/missing")


def test_auth_error_reauth_and_request_id(client):
    resp = _response(401)
    resp.headers = {"X-Request-ID": "req-401"}
    client.session.request = Mock(return_value=resp)
    client.authenticate = Mock()
    with pytest.raises(AuthenticationError) as exc:
        client.request("GET", "/positions")
    client.authenticate.assert_called_once()
    assert exc.value.request_id == "req-401"
    assert exc.value.http_status == 401


def test_server_error_maps_transient_and_request_id(client):
    resp = _response(503)
    resp.headers = {"X-Request-ID": "req-503"}
    client.session.request = Mock(return_value=resp)
    with pytest.raises(TransientBreezeError) as exc:
        client.request("GET", "/positions")
    assert exc.value.request_id == "req-503"
    assert exc.value.http_status == 503


def test_transport_error_maps_to_transient(client):
    client.session.request = Mock(side_effect=requests.RequestException("socket down"))
    with pytest.raises(TransientBreezeError) as exc:
        client.request("GET", "/positions")
    assert exc.value.operation == "/positions"


def test_half_open_probe_failure_raises_circuit_open(client):
    endpoint = "/positions"
    client.circuit._state[endpoint] = CircuitBreakerState.HALF_OPEN
    client.session.get = Mock(return_value=_response(500))
    client.session.request = Mock()
    with pytest.raises(CircuitOpenError):
        client.request("GET", endpoint)
    client.session.request.assert_not_called()


def test_download_security_master_file_requires_token(client):
    client.ensure_authenticated = Mock()
    client.auth_manager.current = Mock(return_value=None)
    with pytest.raises(AuthenticationError):
        client.download_security_master_file("/files/master.csv")


def test_download_security_master_file_success(client):
    fake_record = Mock()
    fake_record.access_token = "tok"
    client.ensure_authenticated = Mock()
    client.auth_manager.current = Mock(return_value=fake_record)

    resp = Mock()
    resp.content = b"csv-data"
    resp.raise_for_status.return_value = None
    client.session.get = Mock(return_value=resp)

    payload = client.download_security_master_file("/files/master.csv")
    assert payload == b"csv-data"
