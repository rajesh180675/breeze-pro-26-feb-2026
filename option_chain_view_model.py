"""View-model assembly for the option-chain page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from option_chain_service import build_multi_expiry_dataset
from option_chain_summary import build_option_chain_summary_payload


@dataclass
class OptionChainMetricsViewModel:
    summary_payload: Dict[str, Any]
    atm: float
    max_pain: float


@dataclass
class OptionChainDisplayStateViewModel:
    display_df: pd.DataFrame
    pinned_strikes: List[int]
    ladder: pd.DataFrame
    selected_strike: Optional[int]
    export_payload: Dict[str, Any]


@dataclass
class OptionChainPageViewModel:
    metrics: OptionChainMetricsViewModel
    display: OptionChainDisplayStateViewModel
    analysis_payload: Dict[str, Any]
    chart_payload: Dict[str, Any]
    compare_caption: Optional[str]


def build_option_chain_page_view_model(
    controls: Any,
    workspace: Dict[str, Any],
    compare_frames: Dict[str, pd.DataFrame],
    base_df: pd.DataFrame,
    selected_strike: Optional[int],
    spot: float,
    expiry_label: str,
    days_to_expiry: int,
) -> OptionChainPageViewModel:
    summary = workspace["summary"]
    expiry_strip = workspace["expiry_strip"]
    summary_payload = build_option_chain_summary_payload(
        spot,
        workspace["atm"],
        summary["pcr"],
        workspace["max_pain"],
        days_to_expiry,
        summary["expected_move"]["expected_move"],
        base_df[base_df["right"] == "Call"]["open_interest"].sum() if "right" in base_df.columns else 0,
        base_df[base_df["right"] == "Put"]["open_interest"].sum() if "right" in base_df.columns else 0,
        expiry_strip,
    )
    compare_dataset = build_multi_expiry_dataset(
        compare_frames,
        "open_interest",
        normalization_mode=controls.normalization_mode,
        spot=spot,
    )
    compare_caption = None
    if controls.chart_tab in {"Compare OI", "Compare IV Smile"} and not compare_dataset.empty:
        compare_caption = f"Comparison mode: {controls.normalization_mode}"
    return OptionChainPageViewModel(
        metrics=OptionChainMetricsViewModel(
            summary_payload=summary_payload,
            atm=workspace["atm"],
            max_pain=workspace["max_pain"],
        ),
        display=OptionChainDisplayStateViewModel(
            display_df=workspace["display_df"],
            pinned_strikes=workspace["pinned_strikes"],
            ladder=workspace["ladder"],
            selected_strike=selected_strike,
            export_payload={
                "enabled": bool(not workspace["display_df"].empty and controls.chain_opt_export),
                "filename": f"option_chain_{controls.inst}_{controls.expiry}.csv",
            },
        ),
        analysis_payload={
            "panel_payload": workspace["commentary_payload"],
            "change_df": workspace["change_df"],
            "top_movers": workspace["top_movers"],
            "session_iv_extremes": workspace["session_iv_extremes"],
            "change_window": controls.change_window,
        },
        chart_payload={
            "chart_tab": controls.chart_tab,
            "display_df": workspace["display_df"],
            "change_df": workspace["change_df"],
            "compare_frames": compare_frames,
            "normalization_mode": controls.normalization_mode,
            "spot": spot,
            "atm": workspace["atm"],
            "max_pain": workspace["max_pain"],
            "selected_strike": selected_strike,
            "expiry_label": expiry_label,
            "expiry_strip": expiry_strip,
            "replay_chart_df": workspace["replay_chart_df"],
            "replay_timestamp": workspace["as_of_ts"],
            "change_window": controls.change_window,
            "gamma_profile": workspace["gamma_profile"],
            "vanna_profile": workspace["vanna_profile"],
            "charm_profile": workspace["charm_profile"],
            "gamma_walls": summary["gamma_walls"],
        },
        compare_caption=compare_caption,
    )
