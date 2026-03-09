import io
import sys
import types

import pandas as pd

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class _DummyBreezeConnect:  # pragma: no cover
        pass

    stub.BreezeConnect = _DummyBreezeConnect
    sys.modules["breeze_connect"] = stub

import app_config as C
from breeze_api import APIResponseValidator
from persistence import TradeDB, export_trades_for_tax
from lib.breeze_client import CircuitBreaker, CircuitBreakerState


def test_export_trades_for_tax_csv_and_excel(tmp_path):
    db = TradeDB()
    db._db_path = str(tmp_path / "tax_export.db")
    db._local = type("L", (), {})()
    db._init_schema()

    db.log_trade(
        stock_code="NIFTY",
        exchange="NFO",
        strike=24000,
        option_type="call",
        expiry="2025-06-26",
        action="buy",
        quantity=25,
        price=100.5,
        trade_id="OID123",
    )

    csv_bytes = export_trades_for_tax(db, "2025-26", "csv")
    assert csv_bytes
    csv_text = csv_bytes.decode("utf-8")
    assert "Trade Date" in csv_text
    assert "OID123" in csv_text

    xlsx_bytes = export_trades_for_tax(db, "2025-26", "excel")
    assert xlsx_bytes
    sheets = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=None)
    assert "Trades" in sheets
    assert "Summary" in sheets


def test_quote_response_validator(monkeypatch):
    monkeypatch.setattr(C, "is_market_open", lambda: True)
    ok, msg = APIResponseValidator.validate_quote_response(
        {
            "success": True,
            "data": {"Success": [{"ltp": "0"}]},
        }
    )
    assert not ok
    assert "Zero LTP" in msg

    ok, msg = APIResponseValidator.validate_quote_response(
        {
            "success": True,
            "data": {"Success": [{"ltp": "101.2", "stock_code": "NIFTY"}]},
        },
        expected_symbol="NIFTY",
    )
    assert ok
    assert msg == ""


def test_order_response_validator_and_sanitize_price():
    ok, msg = APIResponseValidator.validate_order_response(
        {
            "success": True,
            "data": {"Success": [{"order_id": "ABC123"}]},
        }
    )
    assert ok
    assert msg == ""

    assert APIResponseValidator.sanitize_price("1,234.50") == 1234.5
    assert APIResponseValidator.sanitize_price("-1", default=9.0) == 9.0


def test_circuit_breaker_endpoint_state():
    cb = CircuitBreaker(threshold=2, window_seconds=60, open_seconds=1)
    endpoint = "/quotes"

    assert cb.before_request(endpoint) is False
    cb.record_failure(endpoint)
    cb.record_failure(endpoint)

    assert cb._state[endpoint] == CircuitBreakerState.OPEN
