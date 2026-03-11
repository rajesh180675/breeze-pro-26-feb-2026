import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from option_chain_view_model import build_option_chain_page_view_model


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def test_option_chain_page_view_model_groups_render_payloads():
    display_df = _fixture("option_chain_balanced.json")
    workspace = {
        "summary": {
            "pcr": 1.02,
            "expected_move": {"expected_move": 236.0},
            "gamma_walls": [{"strike": 22000, "net_gamma": 1.0}],
        },
        "atm": 22000,
        "max_pain": 22000,
        "display_df": display_df,
        "pinned_strikes": [22000],
        "ladder": pd.DataFrame([{"strike": 22000, "is_selected": 1}]),
        "commentary_payload": {"commentary": ["test"], "alerts": []},
        "gamma_profile": pd.DataFrame([{"strike_price": 22000, "net_gamma": 1.0}]),
        "vanna_profile": pd.DataFrame([{"strike_price": 22000, "net_vanna": 1.0}]),
        "charm_profile": pd.DataFrame([{"strike_price": 22000, "net_charm": 1.0}]),
        "change_df": pd.DataFrame([{"strike": 22000, "option_type": "CE", "open_interest_change": 100}]),
        "top_movers": {"oi_addition": pd.DataFrame([{"strike": 22000}])},
        "session_iv_extremes": pd.DataFrame([{"strike": 22000, "session_iv_high": 0.2}]),
        "as_of_ts": "2026-03-11T09:20:00",
        "replay_chart_df": pd.DataFrame([{"snapshot_ts": "2026-03-11T09:20:00", "strike": 22000, "open_interest": 1000, "option_type": "CE", "iv": 0.2}]),
        "expiry_strip": [{"expiry": "2026-03-26", "atm_iv": 0.18, "expected_move": 236.0}],
    }
    controls = SimpleNamespace(
        inst="NIFTY",
        expiry="2026-03-26",
        change_window="5m",
        chart_tab="Compare OI",
        normalization_mode="ATM %",
        chain_opt_export=True,
    )
    vm = build_option_chain_page_view_model(
        controls,
        workspace,
        {"2026-03-26": display_df},
        display_df,
        22000,
        22020,
        "26 Mar",
        7,
    )
    assert vm.metrics.summary_payload["cards"][1]["value"] == "22,000"
    assert vm.metrics.atm == 22000
    assert vm.analysis_payload["change_window"] == "5m"
    assert vm.chart_payload["chart_tab"] == "Compare OI"
    assert vm.compare_caption == "Comparison mode: ATM %"
    assert vm.display.selected_strike == 22000
    assert vm.display.export_payload["enabled"] is True


def test_option_chain_page_view_model_omits_compare_caption_without_compare_data():
    display_df = _fixture("option_chain_balanced.json")
    workspace = {
        "summary": {
            "pcr": 1.02,
            "expected_move": {"expected_move": 236.0},
            "gamma_walls": [],
        },
        "atm": 22000,
        "max_pain": 22000,
        "display_df": display_df,
        "pinned_strikes": [],
        "ladder": pd.DataFrame(),
        "commentary_payload": {"commentary": [], "alerts": []},
        "gamma_profile": pd.DataFrame(),
        "vanna_profile": pd.DataFrame(),
        "charm_profile": pd.DataFrame(),
        "change_df": pd.DataFrame(),
        "top_movers": {},
        "session_iv_extremes": pd.DataFrame(),
        "as_of_ts": "",
        "replay_chart_df": pd.DataFrame(),
        "expiry_strip": [],
    }
    controls = SimpleNamespace(
        inst="NIFTY",
        expiry="2026-03-26",
        change_window="5m",
        chart_tab="Compare OI",
        normalization_mode="ATM %",
        chain_opt_export=False,
    )

    vm = build_option_chain_page_view_model(
        controls,
        workspace,
        {"2026-03-26": pd.DataFrame()},
        display_df,
        None,
        22020,
        "26 Mar",
        7,
    )

    assert vm.compare_caption is None
    assert vm.display.export_payload["enabled"] is False
