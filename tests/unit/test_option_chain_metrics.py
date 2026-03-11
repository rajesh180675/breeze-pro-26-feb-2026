import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from option_chain_metrics import (
    calculate_expected_move,
    calculate_charm,
    calculate_iv_percentile,
    calculate_iv_zscore,
    calculate_liquidity_score,
    calculate_max_pain,
    calculate_pcr,
    calculate_vanna,
    classify_oi_buildup,
    detect_event_premium,
    detect_gamma_walls,
)


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def test_core_metrics_on_balanced_fixture():
    df = _fixture("option_chain_balanced.json")
    assert round(calculate_pcr(df), 2) == 1.02
    assert calculate_max_pain(df) == 22000
    move = calculate_expected_move(df, spot=22020, atm_strike=22000, days_to_expiry=7)
    assert move["straddle"] == 236.0
    assert move["expected_move"] == 236.0


def test_iv_percentile_zscore_and_buildup_are_deterministic():
    history = [0.15, 0.16, 0.18, 0.2, 0.22]
    assert calculate_iv_percentile(0.2, history) == 80.0
    assert round(calculate_iv_zscore(0.2, history), 4) == 0.7028
    assert classify_oi_buildup(10, 5) == "Long Build-up"
    assert classify_oi_buildup(-2, 10) == "Short Build-up"
    assert classify_oi_buildup(5, -1) == "Short Covering"
    assert classify_oi_buildup(-5, -1) == "Long Unwinding"


def test_liquidity_score_and_gamma_walls():
    df = _fixture("option_chain_call_wall_trend.json")
    score = calculate_liquidity_score(df.iloc[0].to_dict(), freshness_seconds=10)
    assert score > 30
    walls = detect_gamma_walls(df, top_n=2)
    assert len(walls) == 2
    assert int(walls[0]["strike"]) == 22200


def test_event_premium_detector_flags_distortion():
    out = detect_event_premium(0.28, 0.22, threshold=0.03)
    assert out["is_elevated"] is True
    assert out["distortion"] == 0.06


def test_vanna_and_charm_are_non_zero_for_active_contracts():
    expiry = (date.today() + timedelta(days=14)).isoformat()
    vanna = calculate_vanna(spot=22020, strike=22000, expiry=expiry, option_type="CE", iv=0.2)
    charm = calculate_charm(spot=22020, strike=22000, expiry=expiry, option_type="CE", iv=0.2)
    assert abs(vanna) > 0
    assert abs(charm) > 0


def test_placeholder_numeric_values_do_not_break_liquidity_or_iv_normalization():
    score = calculate_liquidity_score(
        {
            "best_bid_price": "—",
            "best_offer_price": "—",
            "bid_qty": "—",
            "offer_qty": "—",
            "volume": "—",
            "open_interest": "—",
            "ltp": "—",
        }
    )
    move = calculate_expected_move(
        pd.DataFrame(
            [
                {"strike_price": 22000, "right": "Call", "ltp": 121, "iv": "—"},
                {"strike_price": 22000, "right": "Put", "ltp": 115, "iv": "—"},
            ]
        ),
        spot=22020,
        atm_strike=22000,
        days_to_expiry=7,
    )
    assert score == 0.0
    assert move["expected_move"] == 236.0
