import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("plotly")

from option_chain_page import build_option_chain_chart
from option_chain_service import enrich_option_chain


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def test_build_option_chain_chart_dispatches_expected_move_and_delta():
    display_df = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2026-03-26", 22020, include_greeks=False)
    change_df = pd.DataFrame(
        [
            {"strike": 22000, "option_type": "CE", "open_interest_change": 1000},
            {"strike": 22000, "option_type": "PE", "open_interest_change": -800},
        ]
    )
    replay_chart_df = pd.DataFrame(
        [
            {"snapshot_ts": "2026-03-11T09:15:00", "strike": 22000, "option_type": "CE", "open_interest": 1000, "iv": 0.18},
            {"snapshot_ts": "2026-03-11T09:20:00", "strike": 22000, "option_type": "PE", "open_interest": 1200, "iv": 0.2},
        ]
    )
    expiry_strip = [{"expiry": "2026-03-26", "atm_iv": 0.18, "expected_move": 236.0}]

    delta_fig = build_option_chain_chart(
        "Delta OI",
        display_df,
        change_df,
        {"2026-03-26": display_df},
        "Absolute",
        22020,
        22000,
        22000,
        22000,
        "26 Mar",
        expiry_strip,
        replay_chart_df,
        "2026-03-11T09:20:00",
        "5m",
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        [],
    )
    expected_fig = build_option_chain_chart(
        "Expected Move",
        display_df,
        change_df,
        {"2026-03-26": display_df},
        "Absolute",
        22020,
        22000,
        22000,
        22000,
        "26 Mar",
        expiry_strip,
        replay_chart_df,
        "2026-03-11T09:20:00",
        "5m",
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        [],
    )

    assert delta_fig.layout.title.text == "Replay Delta/OI Change (5m)"
    assert expected_fig.layout.title.text == "Expected Move by Expiry"


def test_build_option_chain_chart_returns_none_for_unknown_tab():
    fig = build_option_chain_chart(
        "Unknown",
        pd.DataFrame(),
        pd.DataFrame(),
        {},
        "Absolute",
        0.0,
        0.0,
        0.0,
        None,
        "",
        [],
        pd.DataFrame(),
        "",
        "Since Open",
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        [],
    )
    assert fig is None
