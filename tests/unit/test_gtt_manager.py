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


def test_validate_three_leg_sell_rules():
    req = GTTOrderRequest(
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
    ok, err = validate_gtt_request(req)
    assert ok is True
    assert err == ""


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
