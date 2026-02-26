import time
from unittest.mock import Mock

from paper_trading import PaperTradingEngine


class _QuoteClient:
    def __init__(self, ltp=100.0):
        self._ltp = ltp

    def get_quotes(self, **kwargs):
        return {"success": True, "data": {"Success": [{"ltp": self._ltp}]}}


def test_market_order_fills_immediately():
    client = _QuoteClient(ltp=123.0)
    engine = PaperTradingEngine(client)
    engine.enable()
    resp = engine.place_order(
        stock_code="NIFTY", exchange_code="NFO", product="options", action="buy",
        quantity="10", order_type="market", expiry_date="2026-03-27", right="call", strike_price="22000"
    )
    oid = resp["data"]["Success"][0]["order_id"]
    order = [o for o in engine.get_paper_orders() if o.order_id == oid][0]
    assert order.status == "FILLED"
    assert order.fill_price == 123.0


def test_limit_order_fills_on_cross():
    client = _QuoteClient(ltp=120.0)
    engine = PaperTradingEngine(client)
    engine.FILL_CHECK_INTERVAL = 1
    engine.enable()
    resp = engine.place_order(
        stock_code="NIFTY", exchange_code="NFO", product="options", action="buy",
        quantity="5", order_type="limit", price="100", expiry_date="2026-03-27", right="call", strike_price="22000"
    )
    oid = resp["data"]["Success"][0]["order_id"]
    time.sleep(0.2)
    order = [o for o in engine.get_paper_orders() if o.order_id == oid][0]
    assert order.status == "PENDING"

    client._ltp = 99.0
    for _ in range(20):
        time.sleep(0.3)
        order = [o for o in engine.get_paper_orders() if o.order_id == oid][0]
        if order.status == "FILLED":
            break
    assert order.status == "FILLED"


def test_realized_pnl_tracking_on_close():
    client = _QuoteClient(ltp=100.0)
    engine = PaperTradingEngine(client)
    engine.enable()
    engine.place_order(stock_code="NIFTY", exchange_code="NFO", product="options", action="buy", quantity="10", order_type="market", expiry_date="2026-03-27", right="call", strike_price="22000")
    client._ltp = 110.0
    engine.place_order(stock_code="NIFTY", exchange_code="NFO", product="options", action="sell", quantity="10", order_type="market", expiry_date="2026-03-27", right="call", strike_price="22000")
    summary = engine.get_paper_summary()
    assert summary["realized_pnl"] == 100.0
