import sys
import types
from unittest.mock import Mock

fake_mod = types.ModuleType("breeze_connect")
fake_mod.BreezeConnect = object
sys.modules.setdefault("breeze_connect", fake_mod)

from basket_orders import BasketLeg, BasketOrderExecutor, render_basket_results
from breeze_api import BreezeAPIClient, OrderSlicer


def _client():
    c = BreezeAPIClient("k", "s")
    c.connected = True
    c.breeze = Mock()
    return c


def test_place_amo_order_sets_special_flag_yes():
    c = _client()
    c.breeze.place_order.return_value = {"Status": 200, "Success": [{"order_id": "A1"}]}

    resp = c.place_amo_order(
        stock_code="NIFTY",
        exchange_code="NFO",
        product="options",
        action="buy",
        quantity="50",
        order_type="market",
        expiry_date="2026-03-27",
        right="call",
        strike_price="22000",
    )

    assert resp["success"] is True
    kwargs = c.breeze.place_order.call_args.kwargs
    assert kwargs["special_flag"] == "Y"


def test_place_option_plus_order_rejects_blank_stoploss():
    c = _client()

    resp = c.place_option_plus_order(
        stock_code="NIFTY",
        exchange_code="NFO",
        action="buy",
        quantity="50",
        price="100",
        expiry_date="2026-03-27",
        right="call",
        strike_price="22000",
        stoploss="",
    )

    assert resp["success"] is False
    c.breeze.place_order.assert_not_called()


def test_order_slicer_places_expected_slice_quantities(monkeypatch):
    c = _client()
    c.breeze.place_order.side_effect = [
        {"Status": 200, "Success": [{"order_id": "1"}]},
        {"Status": 200, "Success": [{"order_id": "2"}]},
        {"Status": 200, "Success": [{"order_id": "3"}]},
    ]
    monkeypatch.setattr("breeze_api.time.sleep", lambda *_: None)

    slicer = OrderSlicer(c, n_slices=3, interval_seconds=0.01, jitter_pct=0.0)
    out = slicer.execute(
        place_order_kwargs={
            "stock_code": "NIFTY",
            "exchange_code": "NFO",
            "product": "options",
            "action": "buy",
            "order_type": "market",
            "price": "",
            "stoploss": "0",
            "validity": "day",
            "disclosed_quantity": "0",
            "expiry_date": "2026-03-27T06:00:00.000Z",
            "right": "call",
            "strike_price": "22000",
        },
        total_quantity=10,
    )

    assert out["slices_placed"] == 3
    assert out["slices_failed"] == 0
    assert out["total_quantity_placed"] == 10
    placed_quantities = [call.kwargs["quantity"] for call in c.breeze.place_order.call_args_list]
    assert placed_quantities == ["4", "3", "3"]


def test_basket_executor_stops_on_first_failure(monkeypatch):
    c = _client()
    c.breeze.place_order.side_effect = [
        {"Status": 200, "Success": [{"order_id": "OK1"}]},
        {"Status": 400, "Error": "bad", "Success": None},
        {"Status": 200, "Success": [{"order_id": "OK3"}]},
    ]
    monkeypatch.setattr("basket_orders.time.sleep", lambda *_: None)

    legs = [
        BasketLeg("NIFTY", "NFO", "options", "sell", 50, "market", 0, "2026-03-27T06:00:00.000Z", "call", 22000, "L1"),
        BasketLeg("NIFTY", "NFO", "options", "buy", 50, "market", 0, "2026-03-27T06:00:00.000Z", "put", 22000, "L2"),
        BasketLeg("NIFTY", "NFO", "options", "sell", 50, "market", 0, "2026-03-27T06:00:00.000Z", "call", 22100, "L3"),
    ]
    ex = BasketOrderExecutor(c, stop_on_failure=True)
    res = ex.execute(legs)

    assert len(res) == 2
    assert res[0].success is True
    assert res[1].success is False


class _FakeSt:
    def __init__(self):
        self.calls = []

    def success(self, msg):
        self.calls.append(("success", msg))

    def error(self, msg):
        self.calls.append(("error", msg))

    def warning(self, msg):
        self.calls.append(("warning", msg))

    def caption(self, msg):
        self.calls.append(("caption", msg))


def test_render_basket_results_partial_execution_message():
    st = _FakeSt()
    legs = [
        BasketLeg("N", "NFO", "options", "buy", 1, "market", 0, "e", "call", 1, "A"),
        BasketLeg("N", "NFO", "options", "sell", 1, "market", 0, "e", "put", 2, "B"),
    ]
    results = [
        types.SimpleNamespace(leg=legs[0], success=True, order_id="1", message=""),
        types.SimpleNamespace(leg=legs[1], success=False, order_id=None, message="failed"),
    ]

    render_basket_results(results, st_module=st)

    assert any(c[0] == "warning" and "Partial execution" in c[1] for c in st.calls)
    assert len([c for c in st.calls if c[0] == "caption"]) == 2
