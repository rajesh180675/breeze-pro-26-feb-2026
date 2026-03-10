from datetime import date, timedelta

from strategies import (
    AIStrategySuggester,
    PREDEFINED_STRATEGIES,
    calculate_strategy_metrics,
    generate_payoff_data,
    generate_strategy_legs,
    get_strategies_by_view,
)


def test_all_defined_strategy_names_generate_legs():
    for name in PREDEFINED_STRATEGIES:
        legs = generate_strategy_legs(
            strategy_name=name,
            atm_strike=20000,
            strike_gap=50,
            lot_size=25,
            lots=1,
        )
        assert len(legs) > 0, name


def test_iron_condor_has_four_legs():
    legs = generate_strategy_legs("Iron Condor", 20000, 50, 25, 1)
    assert len(legs) == 4


def test_bull_call_spread_has_two_legs_with_correct_sides():
    legs = generate_strategy_legs("Bull Call Spread", 20000, 50, 25, 1)
    assert len(legs) == 2
    assert {leg.action for leg in legs} == {"buy", "sell"}
    assert {leg.option_type for leg in legs} == {"CE"}


def test_calculate_strategy_metrics_returns_max_profit_loss():
    legs = generate_strategy_legs("Iron Condor", 20000, 50, 25, 1)
    for leg in legs:
        leg.premium = 100.0 if leg.action == "sell" else 60.0
    metrics = calculate_strategy_metrics(legs)
    assert metrics["max_profit"] > 0
    assert metrics["max_loss"] < 0
    assert len(metrics["breakevens"]) <= 2


def test_generate_payoff_data_produces_correct_shape():
    legs = generate_strategy_legs("Short Strangle", 20000, 50, 25, 1)
    for leg in legs:
        leg.premium = 100.0
    payoff = generate_payoff_data(legs, center=20000, gap=50, points=200)
    assert payoff is not None
    assert len(payoff) == 200
    assert set(["Underlying", "P&L"]).issubset(payoff.columns)


def test_ai_suggester_returns_result_for_all_regimes():
    suggester = AIStrategySuggester()
    for regime in ["TRENDING_UP", "TRENDING_DOWN", "RANGE_BOUND", "HIGH_VOLATILITY"]:
        out = suggester.suggest(
            regime={"regime": regime, "recommended_strategies": []},
            vix=18.0,
            pcr=1.0,
            trader_win_rates={},
            available_capital=200000,
            days_to_expiry=7,
        )
        assert out
        assert out[0].strategy


def test_get_strategies_by_view_bullish_returns_correct_names():
    bullish = get_strategies_by_view("Bullish")
    assert "Bull Call Spread" in bullish


def test_calendar_spread_generates_two_expiry_legs():
    near = date.today() + timedelta(days=7)
    far = date.today() + timedelta(days=35)
    legs = generate_strategy_legs(
        strategy_name="Calendar Spread",
        atm_strike=20000,
        strike_gap=50,
        lot_size=25,
        lots=1,
        expiry_by_action={"buy": far.isoformat(), "sell": near.isoformat()},
    )
    assert len(legs) == 2
    assert len({leg.expiry for leg in legs}) == 2


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
