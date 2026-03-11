import pandas as pd

from option_chain_workspace import (
    STRIKE_SELECTABLE_CHARTS,
    build_replay_delta_oi_frame,
    option_chain_chart_supports_selection,
    resolve_monitored_strike_defaults,
    resolve_selected_strike,
    style_option_chain_rows,
)


def test_watchlist_restore_and_selected_strike_resolution():
    defaults = resolve_monitored_strike_defaults([22000], [22100, 22200], [22000, 22100, 22200])
    assert defaults == [22000]
    restored = resolve_monitored_strike_defaults([], [22100, 22200], [22000, 22100, 22200])
    assert restored == [22100, 22200]
    assert resolve_selected_strike(None, [21900, 22000, 22100], 22020) == 22000


def test_chart_selection_only_enabled_for_strike_charts():
    assert "OI Profile" in STRIKE_SELECTABLE_CHARTS
    assert option_chain_chart_supports_selection("OI Profile") is True
    assert option_chain_chart_supports_selection("Expected Move") is False
    assert option_chain_chart_supports_selection("Liquidity") is False


def test_replay_delta_view_prefers_window_change_dataset():
    change_df = pd.DataFrame(
        [
            {"strike": 22000, "option_type": "CE", "open_interest_change": 1000},
            {"strike": 22100, "option_type": "PE", "open_interest_change": -500},
        ]
    )
    fallback_df = pd.DataFrame([{"strike_price": 22000, "right": "Call", "oi_change": 25}])
    out = build_replay_delta_oi_frame(change_df, fallback_df)
    assert list(out["right"]) == ["Call", "Put"]
    assert list(out["oi_change"]) == [1000, -500]


def test_style_option_chain_rows_returns_styler():
    df = pd.DataFrame([{"strike_price": 22000, "right": "Call", "ltp": 120}])
    styled = style_option_chain_rows(df, selected_strike=22000, pinned_strikes=[22000], atm=22000, max_pain=22000)
    assert hasattr(styled, "to_html")
