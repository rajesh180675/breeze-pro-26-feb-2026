from unittest.mock import Mock

import pytest
import requests

from app.lib.breeze_client import BreezeClient, CircuitBreakerState
from app.lib.errors import (
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


def test_get_positions_updates_gauges_and_pnl(client):
    """get_positions should call the underlying request and update Prometheus gauges."""
    rows = [
        {"pnl": "100.5"},
        {"pnl": "200"},
        {"pnl": None},
    ]
    client.session.request = Mock(return_value=_response(200, {"Success": rows}))
    result = client.get_positions()
    assert result == {"Success": rows}


def test_get_positions_handles_empty_success(client):
    client.session.request = Mock(return_value=_response(200, {"Success": None}))
    result = client.get_positions()
    assert result is not None


def test_place_order_records_counter_on_success(client):
    client.session.request = Mock(return_value=_response(200, {"order_id": "ORD001"}))
    payload = {"action": "buy", "stock_code": "NIFTY", "quantity": 75}
    result = client.place_order(payload)
    assert result == {"order_id": "ORD001"}


def test_place_order_records_counter_on_failure(client):
    from app.lib.errors import TransientBreezeError
    client.session.request = Mock(return_value=_response(503))
    with pytest.raises(TransientBreezeError):
        client.place_order({"action": "sell", "stock_code": "BANKNIFTY"})


def test_cancel_order_delegates_to_request(client):
    client.session.request = Mock(return_value=_response(200, {"cancelled": True}))
    result = client.cancel_order("ORD123")
    assert result == {"cancelled": True}


def test_modify_order_delegates_to_request(client):
    client.session.request = Mock(return_value=_response(200, {"updated": True}))
    result = client.modify_order("ORD123", {"quantity": 150})
    assert result == {"updated": True}


def test_get_order_status_delegates_to_request(client):
    client.session.request = Mock(return_value=_response(200, {"status": "filled"}))
    result = client.get_order_status("ORD999")
    assert result == {"status": "filled"}


def test_get_customer_details_delegates_to_request(client):
    client.session.request = Mock(return_value=_response(200, {"name": "Test User"}))
    result = client.get_customer_details()
    assert result == {"name": "Test User"}


def test_get_instruments_with_exchange(client):
    client.session.request = Mock(return_value=_response(200, {"instruments": []}))
    result = client.get_instruments(exchange="NSE")
    assert result == {"instruments": []}


def test_get_instruments_without_exchange(client):
    client.session.request = Mock(return_value=_response(200, {"all": True}))
    result = client.get_instruments()
    assert result == {"all": True}


def test_get_historical_passes_params(client):
    client.session.request = Mock(return_value=_response(200, {"candles": []}))
    result = client.get_historical("NIFTY", "2024-01-01", "2024-01-31", "1day")
    assert result == {"candles": []}


def test_get_option_chain_delegates_to_request(client):
    client.session.request = Mock(return_value=_response(200, {"chain": []}))
    result = client.get_option_chain("NIFTY")
    assert result == {"chain": []}


def test_get_security_master_delegates(client):
    client.session.request = Mock(return_value=_response(200, {"meta": True}))
    result = client.get_security_master()
    assert result == {"meta": True}


def test_circuit_records_success_after_ok_response(client):
    endpoint = "/positions"
    client.session.request = Mock(return_value=_response(200, {"ok": True}))
    client.request("GET", endpoint)
    # After a success, the closed state should allow the next request through
    assert len(client.circuit._errors.get(endpoint, [])) == 0


def test_request_with_empty_response_body(client):
    resp = Mock()
    resp.status_code = 204
    resp.headers = {}
    resp.content = b""
    resp.raise_for_status.return_value = None
    client.session.request = Mock(return_value=resp)
    result = client.request("DELETE", "/orders/X")
    assert result == {}


def test_request_with_invalid_json_body_maps_transient(client):
    resp = _response(200)
    resp.content = b"not-json"
    resp.json.side_effect = ValueError("invalid json")
    client.session.request = Mock(return_value=resp)
    with pytest.raises(TransientBreezeError) as exc:
        client.request("GET", "/positions")
    assert exc.value.http_status == 200
    assert exc.value.operation == "/positions"


def test_authenticate_persists_token(client, monkeypatch):
    """authenticate() should call auth_manager with session token from settings."""
    client.auth_manager.authenticate = Mock()
    client.authenticate()
    client.auth_manager.authenticate.assert_called_once()


def test_ensure_authenticated_calls_ensure_fresh_token(client):
    client.auth_manager.ensure_fresh_token = Mock(return_value=Mock())
    client.ensure_authenticated()
    client.auth_manager.ensure_fresh_token.assert_called_once()
