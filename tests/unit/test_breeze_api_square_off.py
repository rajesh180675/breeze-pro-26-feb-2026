import sys
import types
from unittest.mock import Mock

# Prevent network side effects from real breeze_connect package import-time behavior.
fake_mod = types.ModuleType("breeze_connect")
fake_mod.BreezeConnect = object
sys.modules.setdefault("breeze_connect", fake_mod)

from breeze_api import BreezeAPIClient


def _make_client():
    client = BreezeAPIClient("key", "secret")
    client.connected = True
    client.breeze = Mock()
    return client


def test_square_off_uses_native_sdk_method_not_place_order():
    client = _make_client()
    client.breeze.square_off.return_value = {"Status": 200, "Success": {"order_id": "1"}}

    resp = client.square_off(
        exchange_code="NFO",
        product="options",
        stock_code="NIFTY",
        quantity="50",
        price="",
        action="buy",
        order_type="market",
        expiry_date="2026-03-04",
        right="call",
        strike_price="22000",
    )

    assert resp["success"] is True
    client.breeze.square_off.assert_called_once()
    client.breeze.place_order.assert_not_called()


def test_square_off_option_position_market_uses_empty_price_and_native_square_off():
    client = _make_client()
    client.breeze.square_off.return_value = {"Status": 200, "Success": {"order_id": "2"}}

    position = {
        "stock_code": "NIFTY",
        "exchange_code": "NFO",
        "expiry_date": "2026-03-04",
        "strike_price": "22000",
        "right": "CE",
        "quantity": "100",
        "action": "sell",
    }

    client.square_off_option_position(position)

    kwargs = client.breeze.square_off.call_args.kwargs
    assert kwargs["price"] == ""
    assert kwargs["action"] == "buy"
    assert kwargs["quantity"] == "100"


def test_square_off_option_position_partial_quantity_passed_as_string():
    client = _make_client()
    client.breeze.square_off.return_value = {"Status": 200, "Success": {"order_id": "3"}}

    position = {
        "stock_code": "NIFTY",
        "exchange_code": "NFO",
        "expiry_date": "2026-03-04",
        "strike_price": "22000",
        "right": "PE",
        "quantity": "4",
        "action": "buy",
    }

    client.square_off_option_position(position, quantity=2, order_type="market")

    kwargs = client.breeze.square_off.call_args.kwargs
    assert kwargs["quantity"] == "2"
    assert kwargs["action"] == "sell"


def test_square_off_option_position_limit_sets_price_string():
    client = _make_client()
    client.breeze.square_off.return_value = {"Status": 200, "Success": {"order_id": "4"}}

    position = {
        "stock_code": "NIFTY",
        "exchange_code": "NFO",
        "expiry_date": "2026-03-04",
        "strike_price": "22000",
        "option_type": "CE",
        "quantity": "10",
        "action": "sell",
    }

    client.square_off_option_position(position, quantity=5, order_type="limit", limit_price=123.45)

    kwargs = client.breeze.square_off.call_args.kwargs
    assert kwargs["order_type"] == "limit"
    assert kwargs["price"] == "123.45"
    assert kwargs["quantity"] == "5"
