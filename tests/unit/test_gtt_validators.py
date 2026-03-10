from gtt_manager import (
    GTTLegType,
    GTTLeg,
    GTTOrderRequest,
    GTTType,
    validate_gtt_request,
)


def _base_req():
    return GTTOrderRequest(
        gtt_type=GTTType.SINGLE,
        stock_code="NIFTY",
        exchange_code="NFO",
        product="options",
        quantity="75",
        expiry_date="2026-03-26",
        right="call",
        strike_price="22000",
        index_or_stock="index",
        trade_date="2026-03-10",
        order_details=[
            GTTLeg(
                gtt_leg_type=GTTLegType.STOPLOSS,
                trigger_price="100.0",
                order_type="limit",
                limit_price="101.0",
                action="sell",
            )
        ],
    )


def test_validate_gtt_request_accepts_valid_single_leg():
    ok, msg = validate_gtt_request(_base_req())
    assert ok is True
    assert msg == ""
