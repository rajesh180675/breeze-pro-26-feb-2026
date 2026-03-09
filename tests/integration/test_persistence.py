import pytest

from persistence import TradeDB

pytestmark = pytest.mark.integration


def test_persistence_write_and_readback():
    db = TradeDB()
    ok = db.log_trade(
        stock_code="NIFTY",
        exchange="NFO",
        strike=22000,
        option_type="CE",
        expiry="2026-03-26",
        action="buy",
        quantity=75,
        price=10.0,
        order_type="market",
        notes="integration-test",
    )
    assert ok is True
    rows = db.get_trades(limit=5)
    assert isinstance(rows, list)
