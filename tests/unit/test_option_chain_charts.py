import json
from pathlib import Path

import pandas as pd
import pytest

plotly = pytest.importorskip("plotly")

from option_chain_charts import (
    build_charm_exposure_figure,
    build_delta_oi_profile_figure,
    build_expected_move_figure,
    build_gamma_exposure_figure,
    build_iv_smile_figure,
    build_liquidity_scatter_figure,
    build_multi_expiry_iv_smile_figure,
    build_multi_expiry_oi_figure,
    build_oi_heatmap_figure,
    build_oi_profile_figure,
    build_replay_delta_oi_figure,
    build_skew_shift_replay_figure,
    build_term_structure_figure,
    build_vanna_exposure_figure,
)
from option_chain_service import build_charm_profile, build_gamma_profile, build_vanna_profile, enrich_option_chain


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def test_core_option_chain_figures_render():
    df = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2026-03-26", 22020, include_greeks=False)
    oi_fig = build_oi_profile_figure(df, atm=22000, max_pain=22000, selected_strike=22100)
    delta_fig = build_delta_oi_profile_figure(df, atm=22000, selected_strike=22100)
    smile_fig = build_iv_smile_figure(df, atm=22000, selected_expiry="26 Mar", selected_strike=22100)
    liquidity_fig = build_liquidity_scatter_figure(df)
    assert len(oi_fig.data) == 2
    assert len(delta_fig.data) == 2
    assert len(smile_fig.data) == 2
    assert len(liquidity_fig.data) == 1
    annotation_text = [annotation.text for annotation in oi_fig.layout.annotations]
    assert "ATM" in annotation_text
    assert "Selected" in annotation_text


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
    heatmap_fig = build_oi_heatmap_figure(heatmap_df, replay_timestamp="2026-03-11T09:16:00")
    assert len(term_fig.data) == 1
    assert len(exp_fig.data) == 1
    assert len(gamma_fig.data) == 1
    assert len(heatmap_fig.data) == 1
    assert len(heatmap_fig.layout.shapes) == 1


def test_multi_expiry_and_skew_replay_figures_render():
    cur = _fixture("option_chain_balanced.json")
    nxt = _fixture("option_chain_expiry_day.json")
    oi_fig = build_multi_expiry_oi_figure({"2026-03-26": cur, "2026-04-02": nxt}, normalization_mode="ATM Offset", spot=22020)
    iv_fig = build_multi_expiry_iv_smile_figure({"2026-03-26": cur, "2026-04-02": nxt}, normalization_mode="ATM %", spot=22020)
    replay_df = pd.DataFrame(
        [
            {"snapshot_ts": "2026-03-11T09:15:00", "option_type": "CE", "iv": 0.18},
            {"snapshot_ts": "2026-03-11T09:15:00", "option_type": "PE", "iv": 0.20},
            {"snapshot_ts": "2026-03-11T09:20:00", "option_type": "CE", "iv": 0.17},
            {"snapshot_ts": "2026-03-11T09:20:00", "option_type": "PE", "iv": 0.22},
        ]
    )
    skew_fig = build_skew_shift_replay_figure(replay_df, replay_timestamp="2026-03-11T09:20:00")
    assert len(oi_fig.data) == 2
    assert len(iv_fig.data) == 2
    assert len(skew_fig.data) == 1
    assert oi_fig.layout.xaxis.title.text == "ATM Offset"
    assert iv_fig.layout.xaxis.title.text == "ATM %"
    assert len(skew_fig.layout.shapes) == 1


def test_replay_delta_oi_figure_renders_timestamp_context():
    change_df = pd.DataFrame(
        [
            {"strike": 22000, "option_type": "CE", "open_interest_change": 1000},
            {"strike": 22000, "option_type": "PE", "open_interest_change": -600},
        ]
    )
    fig = build_replay_delta_oi_figure(
        change_df,
        atm=22000,
        selected_strike=22000,
        replay_timestamp="2026-03-11T09:20:00",
        change_window="15m",
    )
    assert len(fig.data) == 2
    assert fig.layout.title.text == "Replay Delta/OI Change (15m)"
    assert any("As of 2026-03-11T09:20:00" in annotation.text for annotation in fig.layout.annotations)


def test_vanna_and_charm_figures_render():
    df = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2099-03-26", 22020, include_greeks=False)
    vanna_fig = build_vanna_exposure_figure(build_vanna_profile(df))
    charm_fig = build_charm_exposure_figure(build_charm_profile(df))
    assert len(vanna_fig.data) == 1
    assert len(charm_fig.data) == 1
