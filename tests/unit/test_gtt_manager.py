import sys
import types

fake_mod = types.ModuleType("breeze_connect")
fake_mod.BreezeConnect = object
sys.modules.setdefault("breeze_connect", fake_mod)

from gtt_manager import (
    GTTLeg,
    GTTLegType,
    GTTManager,
    GTTOrderRequest,
    GTTStatus,
    GTTType,
    validate_gtt_request,
)
from persistence import TradeDB


def _reset_gtt_table(db: TradeDB):
    conn = db._get_conn()
    conn.execute("DELETE FROM gtt_orders")
    conn.commit()


class _FakeClient:
    def __init__(self):
        self.calls = []

    def call_sdk(self, method_name, retryable=True, **kwargs):
        self.calls.append((method_name, retryable, kwargs))
        if "place_order" in method_name:
            return {"success": True, "data": {"Success": {"gtt_order_id": "GTT123"}}}
        if method_name == "gtt_order_book":
            return {
                "success": True,
                "data": {"Success": [{"gtt_order_id": "GTT123", "status": "triggered"}]},
            }
        return {"success": True, "data": {"Success": {}}}


class _ChunkedOrderBookClient(_FakeClient):
    def call_sdk(self, method_name, retryable=True, **kwargs):
        self.calls.append((method_name, retryable, kwargs))
        if method_name == "gtt_order_book":
            chunk_no = sum(1 for name, _, _ in self.calls if name == "gtt_order_book")
            return {
                "success": True,
                "data": {"Success": [{"gtt_order_id": f"GTT{chunk_no}", "status": "active"}]},
            }
        return {"success": True, "data": {"Success": {}}}


def _base_three_leg_req() -> GTTOrderRequest:
    return GTTOrderRequest(
        exchange_code="NFO",
        stock_code="NIFTY",
        product="options",
        quantity="50",
        expiry_date="2026-03-27",
        right="call",
        strike_price="22000",
        gtt_type=GTTType.THREE_LEG,
        index_or_stock="index",
        trade_date="2026-03-27",
        fresh_order_action="sell",
        fresh_order_price="100",
        order_details=[
            GTTLeg(GTTLegType.TARGET, "buy", "90", "88"),
            GTTLeg(GTTLegType.STOPLOSS, "buy", "110", "112"),
        ],
    )


def test_validate_three_leg_sell_rules():
    ok, err = validate_gtt_request(_base_three_leg_req())
    assert ok is True
    assert err == ""


def test_validate_rejects_invalid_target_for_sell_entry():
    req = _base_three_leg_req()
    req.order_details[0] = GTTLeg(GTTLegType.TARGET, "buy", "105", "103")
    ok, err = validate_gtt_request(req)
    assert ok is False
    assert "Target trigger" in err


def test_place_three_leg_calls_sdk_method_with_expected_payload():
    db = TradeDB()
    client = _FakeClient()
    mgr = GTTManager(client, db)
    _reset_gtt_table(db)

    req = _base_three_leg_req()
    resp = mgr.place_three_leg(req)
    assert resp["success"] is True

    method, retryable, kwargs = client.calls[-1]
    assert method == "gtt_three_leg_place_order"
    assert retryable is False
    assert kwargs["gtt_type"] == "THREE_LEG"
    assert kwargs["stock_code"] == "NIFTY"
    assert kwargs["quantity"] == "50"

    records = mgr.get_all_gtts()
    assert any(r.gtt_order_id == "GTT123" and r.entry_price == 100.0 for r in records)


def test_place_single_leg_persists_record():
    db = TradeDB()
    client = _FakeClient()
    mgr = GTTManager(client, db)
    _reset_gtt_table(db)

    req = GTTOrderRequest(
        exchange_code="NFO",
        stock_code="NIFTY",
        product="options",
        quantity="50",
        expiry_date="2026-03-27",
        right="call",
        strike_price="22000",
        gtt_type=GTTType.SINGLE,
        index_or_stock="index",
        trade_date="2026-03-27",
        order_details=[GTTLeg(GTTLegType.STOPLOSS, "buy", "120", "122")],
    )

    resp = mgr.place_single_leg(req)
    assert resp["success"] is True
    active = mgr.get_active_gtts()
    assert any(r.gtt_order_id == "GTT123" for r in active)


def test_cancel_routes_based_on_record_type():
    db = TradeDB()
    client = _FakeClient()
    mgr = GTTManager(client, db)
    _reset_gtt_table(db)

    req = _base_three_leg_req()
    mgr.place_three_leg(req)

    result = mgr.cancel("GTT123")
    assert result["success"] is True
    method, _, _ = client.calls[-1]
    assert method == "gtt_three_leg_cancel_order"


def test_get_order_book_splits_large_date_ranges():
    db = TradeDB()
    client = _ChunkedOrderBookClient()
    mgr = GTTManager(client, db)

    resp = mgr.get_order_book(exchange_code="NFO", from_date="2026-01-01", to_date="2026-01-25")

    assert resp["success"] is True
    order_book_calls = [call for call in client.calls if call[0] == "gtt_order_book"]
    assert len(order_book_calls) == 3
    assert order_book_calls[0][2]["from_date"] == "2026-01-01T06:00:00.000Z"
    assert order_book_calls[0][2]["to_date"] == "2026-01-10T06:00:00.000Z"
    assert order_book_calls[1][2]["from_date"] == "2026-01-11T06:00:00.000Z"
    assert order_book_calls[1][2]["to_date"] == "2026-01-20T06:00:00.000Z"
    assert order_book_calls[2][2]["from_date"] == "2026-01-21T06:00:00.000Z"
    assert order_book_calls[2][2]["to_date"] == "2026-01-25T06:00:00.000Z"
    assert [item["gtt_order_id"] for item in resp["data"]["Success"]] == ["GTT1", "GTT2", "GTT3"]


def test_sync_skips_api_when_no_active_gtts():
    db = TradeDB()
    client = _FakeClient()
    mgr = GTTManager(client, db)
    _reset_gtt_table(db)

    n = mgr.sync_with_api("NFO")

    assert n == 0
    assert not any(method == "gtt_order_book" for method, _, _ in client.calls)


def test_sync_updates_status_to_triggered():
    db = TradeDB()
    client = _FakeClient()
    mgr = GTTManager(client, db)
    _reset_gtt_table(db)

    req = GTTOrderRequest(
        exchange_code="NFO",
        stock_code="NIFTY",
        product="options",
        quantity="50",
        expiry_date="2026-03-27",
        right="call",
        strike_price="22000",
        gtt_type=GTTType.SINGLE,
        index_or_stock="index",
        trade_date="2026-03-27",
        order_details=[GTTLeg(GTTLegType.STOPLOSS, "buy", "120", "122")],
    )
    mgr.place_single_leg(req)

    n = mgr.sync_with_api("NFO")
    assert n >= 1
    rec = [r for r in mgr.get_all_gtts() if r.gtt_order_id == "GTT123"][0]
    assert rec.status == GTTStatus.TRIGGERED
