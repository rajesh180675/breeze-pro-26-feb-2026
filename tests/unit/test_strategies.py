from strategies import generate_strategy_legs


def test_generate_strategy_legs_snaps_to_available_strikes():
    legs = generate_strategy_legs(
        strategy_name="Short Strangle",
        atm_strike=19950,
        strike_gap=50,
        lot_size=25,
        lots=1,
        available_strikes={19800, 19900, 20000},
    )

    assert len(legs) == 2
    assert {leg.strike for leg in legs} == {19800, 20000}


def test_generate_strategy_legs_without_available_strikes_uses_raw_levels():
    legs = generate_strategy_legs(
        strategy_name="Short Strangle",
        atm_strike=19950,
        strike_gap=50,
        lot_size=25,
        lots=1,
        available_strikes=None,
    )

    assert {leg.strike for leg in legs} == {19850, 20050}
