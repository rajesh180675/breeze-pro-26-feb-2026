"""Rendering helpers for the option-chain page."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import pandas as pd
import streamlit as st

from app.application.option_chain.charts import (
    build_charm_exposure_figure,
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
from app.domain.option_chain.workspace import apply_selected_strike, extract_dataframe_selection_rows, extract_plotly_selected_strike, option_chain_chart_supports_selection, style_option_chain_rows


def build_option_chain_chart(chart_tab: str, display_df: pd.DataFrame, change_df: pd.DataFrame, compare_frames: Dict[str, pd.DataFrame], normalization_mode: str, spot: float, atm: float, max_pain: float, selected_strike: Optional[int], expiry_label: str, expiry_strip: Sequence[Dict[str, Any]], replay_chart_df: pd.DataFrame, replay_timestamp: str, change_window: str, gamma_profile: pd.DataFrame, vanna_profile: pd.DataFrame, charm_profile: pd.DataFrame, gamma_walls: Sequence[Dict[str, Any]]):
    if chart_tab == "OI Profile":
        return build_oi_profile_figure(display_df, atm=atm, max_pain=max_pain, selected_strike=float(selected_strike or 0))
    if chart_tab == "Delta OI":
        return build_replay_delta_oi_figure(change_df, atm=atm, selected_strike=float(selected_strike or 0), replay_timestamp=replay_timestamp, change_window=change_window)
    if chart_tab == "IV Smile":
        return build_iv_smile_figure(display_df, atm=atm, selected_expiry=expiry_label, selected_strike=float(selected_strike or 0))
    if chart_tab == "Compare OI":
        return build_multi_expiry_oi_figure(compare_frames, normalization_mode=normalization_mode, spot=spot, selected_strike=float(selected_strike or 0))
    if chart_tab == "Compare IV Smile":
        return build_multi_expiry_iv_smile_figure(compare_frames, normalization_mode=normalization_mode, spot=spot, selected_strike=float(selected_strike or 0))
    if chart_tab == "Term Structure":
        return build_term_structure_figure(expiry_strip)
    if chart_tab == "Expected Move":
        return build_expected_move_figure(expiry_strip, spot)
    if chart_tab == "OI Heatmap":
        return build_oi_heatmap_figure(replay_chart_df, replay_timestamp=replay_timestamp)
    if chart_tab == "Skew Replay":
        return build_skew_shift_replay_figure(replay_chart_df, replay_timestamp=replay_timestamp)
    if chart_tab == "Gamma":
        return build_gamma_exposure_figure(gamma_profile, walls=list(gamma_walls), selected_strike=float(selected_strike or 0))
    if chart_tab == "Vanna":
        return build_vanna_exposure_figure(vanna_profile, selected_strike=float(selected_strike or 0))
    if chart_tab == "Charm":
        return build_charm_exposure_figure(charm_profile, selected_strike=float(selected_strike or 0))
    if chart_tab == "Liquidity":
        return build_liquidity_scatter_figure(display_df)
    return None


def render_option_chain_display(view: str, display_df: pd.DataFrame, ladder: pd.DataFrame, selected_strike: Optional[int], pinned_strikes: Sequence[int], atm: float, max_pain: float, all_strikes: Sequence[int]) -> Optional[int]:
    st.caption(f"Selected strike: {selected_strike}" if selected_strike else "Selected strike: none")
    if view == "Ladder":
        if ladder.empty:
            st.info("No ladder rows to display.")
            return selected_strike
        ladder_selection = st.dataframe(style_option_chain_rows(ladder, selected_strike, pinned_strikes=pinned_strikes, atm=atm, max_pain=max_pain), height=640, hide_index=True, width="stretch", key="oc_ladder_table", on_select="rerun", selection_mode="single-row")
        selected_rows = extract_dataframe_selection_rows(ladder_selection)
        if selected_rows:
            selected_idx = selected_rows[0]
            if 0 <= selected_idx < len(ladder):
                return apply_selected_strike(selected_strike, int(ladder.iloc[selected_idx]["strike"]), all_strikes, atm)
        return selected_strike
    if view == "Calls Only":
        st.dataframe(style_option_chain_rows(display_df[display_df["right"] == "Call"].copy(), selected_strike, pinned_strikes=pinned_strikes, atm=atm, max_pain=max_pain), height=640, hide_index=True, width="stretch")
        return selected_strike
    if view == "Puts Only":
        st.dataframe(style_option_chain_rows(display_df[display_df["right"] == "Put"].copy(), selected_strike, pinned_strikes=pinned_strikes, atm=atm, max_pain=max_pain), height=640, hide_index=True, width="stretch")
        return selected_strike
    st.dataframe(style_option_chain_rows(display_df, selected_strike, pinned_strikes=pinned_strikes, atm=atm, max_pain=max_pain), height=640, hide_index=True, width="stretch")
    return selected_strike


def render_option_chain_analysis(panel_payload: Dict[str, Any], change_df: pd.DataFrame, top_movers: Dict[str, pd.DataFrame], session_iv_extremes: pd.DataFrame, change_window: str, section_fn) -> None:
    section_fn("🧠 Commentary")
    for line in panel_payload["commentary"]:
        st.write(f"- {line}")
    section_fn("🚨 Alerts")
    if panel_payload["alerts"]:
        for alert in panel_payload["alerts"]:
            st.write(f"- [{alert['severity'].upper()}] {alert['message']}")
    else:
        st.caption("No deterministic alerts triggered.")
    if not change_df.empty:
        section_fn(f"⏱ {change_window} Movers")
        for mover_label, mover_key in (("OI Addition", "oi_addition"), ("OI Reduction", "oi_reduction"), ("Volume Burst", "volume_burst"), ("Spread Widening", "spread_widening")):
            movers = top_movers.get(mover_key)
            if movers is not None and not movers.empty:
                st.caption(mover_label)
                display_cols = [col for col in ["strike", "option_type", "open_interest_change", "volume_change", "iv_change", "spread_change"] if col in movers.columns]
                st.dataframe(movers[display_cols].head(3), hide_index=True, width="stretch")
    if not session_iv_extremes.empty:
        section_fn("📉 Session IV Range")
        st.dataframe(session_iv_extremes.head(6), hide_index=True, width="stretch")


def render_option_chain_chart(fig, chart_tab: str, selected_strike: Optional[int], all_strikes: Sequence[int], atm: float) -> Optional[int]:
    if fig is None:
        return selected_strike
    plotly_selection = st.plotly_chart(fig, use_container_width=True, key="oc_chain_chart", on_select="rerun" if option_chain_chart_supports_selection(chart_tab) else "ignore", selection_mode="points", config={"displaylogo": False})
    if not option_chain_chart_supports_selection(chart_tab):
        return selected_strike
    plotted_strike = extract_plotly_selected_strike(plotly_selection)
    return apply_selected_strike(selected_strike, plotted_strike, all_strikes, atm)
