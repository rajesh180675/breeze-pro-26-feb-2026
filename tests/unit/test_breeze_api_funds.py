import sys
import types
from unittest.mock import Mock

fake_mod = types.ModuleType("breeze_connect")
fake_mod.BreezeConnect = object
sys.modules.setdefault("breeze_connect", fake_mod)

from breeze_api import BreezeAPIClient


def _mk_client():
    c = BreezeAPIClient("k", "s")
    c.connected = True
    c.breeze = Mock()
    return c


def test_set_funds_calls_sdk_non_retryable():
    c = _mk_client()
    c.breeze.set_funds.return_value = {"Status": 200, "Success": {"ok": True}}

    resp = c.set_funds("Deposit", "10000", "FNO")
    assert resp["success"] is True
    kwargs = c.breeze.set_funds.call_args.kwargs
    assert kwargs["transaction_type"] == "Deposit"
    assert kwargs["amount"] == "10000"
    assert kwargs["segment"] == "FNO"


def test_add_margin_calls_sdk_non_retryable():
    c = _mk_client()
    c.breeze.add_margin.return_value = {"Status": 200, "Success": {"ok": True}}

    resp = c.add_margin(
        product_type="options",
        stock_code="NIFTY",
        exchange_code="NFO",
        add_amount="5000",
        margin_from_segment="Equity",
        margin_to_segment="FNO",
    )
    assert resp["success"] is True
    kwargs = c.breeze.add_margin.call_args.kwargs
    assert kwargs["product_type"] == "options"
    assert kwargs["stock_code"] == "NIFTY"
    assert kwargs["exchange_code"] == "NFO"
    assert kwargs["add_amount"] == "5000"
