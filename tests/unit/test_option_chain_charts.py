import json
from pathlib import Path

import pandas as pd
import pytest

plotly = pytest.importorskip("plotly")

from option_chain_charts import (
    build_delta_oi_profile_figure,
    build_expected_move_figure,
    build_gamma_exposure_figure,
    build_iv_smile_figure,
    build_liquidity_scatter_figure,
    build_oi_heatmap_figure,
    build_oi_profile_figure,
    build_term_structure_figure,
)
from option_chain_service import build_gamma_profile, enrich_option_chain


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def test_core_option_chain_figures_render():
    df = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2026-03-26", 22020, include_greeks=False)
    oi_fig = build_oi_profile_figure(df, atm=22000, max_pain=22000)
    delta_fig = build_delta_oi_profile_figure(df, atm=22000)
    smile_fig = build_iv_smile_figure(df, atm=22000, selected_expiry="26 Mar")
    liquidity_fig = build_liquidity_scatter_figure(df)
    assert len(oi_fig.data) == 2
    assert len(delta_fig.data) == 2
    assert len(smile_fig.data) == 2
    assert len(liquidity_fig.data) == 1
    assert any(annotation.text == "ATM" for annotation in oi_fig.layout.annotations)


def test_term_structure_heatmap_and_gamma_figures_render():
    summaries = [
        {"expiry": "2026-03-26", "atm_iv": 0.18, "expected_move": 236.0},
        {"expiry": "2026-04-02", "atm_iv": 0.21, "expected_move": 280.0},
    ]
    term_fig = build_term_structure_figure(summaries)
    exp_fig = build_expected_move_figure(summaries, 22020)
    heatmap_df = pd.DataFrame(
        [
            {"snapshot_ts": "2026-03-11T09:15:00", "strike": 22000, "open_interest": 1000},
            {"snapshot_ts": "2026-03-11T09:16:00", "strike": 22000, "open_interest": 1100},
            {"snapshot_ts": "2026-03-11T09:15:00", "strike": 22100, "open_interest": 900},
        ]
    )
    gamma_profile = build_gamma_profile(enrich_option_chain(_fixture("option_chain_call_wall_trend.json"), "NIFTY", "2026-03-26", 22100, include_greeks=False))
    gamma_fig = build_gamma_exposure_figure(gamma_profile, walls=[{"strike": 22200, "net_gamma": 1.0}])
    heatmap_fig = build_oi_heatmap_figure(heatmap_df)
    assert len(term_fig.data) == 1
    assert len(exp_fig.data) == 1
    assert len(gamma_fig.data) == 1
    assert len(heatmap_fig.data) == 1
