from datetime import date

from futures import (
    FuturesOrderRequest,
    calculate_basis,
    get_futures_expiries,
    validate_futures_order,
)


def test_get_futures_expiries_returns_count_and_future_dates():
    expiries = get_futures_expiries("NIFTY", count=3)
    assert len(expiries) == 3
    today = date.today().isoformat()
    assert all(e > today for e in expiries)


def test_calculate_basis():
    assert calculate_basis(22125.5, 22000.0) == 125.5


def test_validate_futures_order_rejects_invalid_limit_price():
    req = FuturesOrderRequest(
        stock_code="NIFTY",
        exchange_code="NFO",
        expiry_date="2026-03-26",
        action="buy",
        lots=1,
        lot_size=75,
        order_type="limit",
        limit_price=0,
    )
    ok, msg = validate_futures_order(req, available_margin=1_000_000)
    assert ok is False
    assert "Limit price" in msg
