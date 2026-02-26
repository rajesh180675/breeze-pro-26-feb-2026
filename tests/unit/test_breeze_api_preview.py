import sys
import types
from unittest.mock import Mock

fake_mod = types.ModuleType("breeze_connect")
fake_mod.BreezeConnect = object
sys.modules.setdefault("breeze_connect", fake_mod)

from breeze_api import BreezeAPIClient


def _make_client():
    c = BreezeAPIClient("k", "s")
    c.connected = True
    c.breeze = Mock()
    return c


def test_preview_order_calls_sdk_with_expected_fields():
    client = _make_client()
    client.breeze.preview_order.return_value = {"Status": 200, "Success": {"total_brokerage": 12.3}}

    resp = client.preview_order(
        stock_code="NIFTY",
        exchange_code="NFO",
        product="options",
        order_type="limit",
        price="100",
        action="sell",
        quantity="50",
        expiry_date="2026-03-27",
        right="call",
        strike_price="22000",
    )

    assert resp["success"] is True
    kwargs = client.breeze.preview_order.call_args.kwargs
    assert kwargs["stock_code"] == "NIFTY"
    assert kwargs["order_type"] == "limit"
    assert kwargs["action"] == "sell"
    assert kwargs["quantity"] == "50"


def test_limit_calculator_calls_sdk_and_returns_envelope():
    client = _make_client()
    client.breeze.limit_calculator.return_value = {"Status": 200, "Success": {"limit_rate": "123.5"}}

    resp = client.limit_calculator(
        strike_price="22000",
        product_type="optionplus",
        expiry_date="2026-03-27",
        underlying="NIFTY",
        exchange_code="NFO",
        order_flow="Buy",
        stop_loss_trigger="90",
        option_type="Call",
        limit_rate="100",
        fresh_order_limit="101",
    )

    assert resp["success"] is True
    kwargs = client.breeze.limit_calculator.call_args.kwargs
    assert kwargs["product_type"] == "optionplus"
    assert kwargs["underlying"] == "NIFTY"
    assert kwargs["stop_loss_trigger"] == "90"
