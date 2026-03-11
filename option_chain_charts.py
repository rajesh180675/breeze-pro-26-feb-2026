"""Plotly charts for the option-chain workspace."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import pandas as pd
import plotly.graph_objects as go

from option_chain_utils import estimate_atm_strike


def _empty_figure(title: str, message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(title=title, annotations=[{"text": message, "showarrow": False}], hovermode="x unified")
    return fig


def _marker_annotation(fig: go.Figure, x: float, text: str, color: str) -> None:
    fig.add_vline(x=x, line_dash="dot", line_color=color, opacity=0.8)
    fig.add_annotation(x=x, y=1.02, yref="paper", text=text, showarrow=False, font={"color": color})


def _selected_marker(fig: go.Figure, selected_strike: Optional[float]) -> None:
    if selected_strike:
        _marker_annotation(fig, float(selected_strike), "Selected", "#17a2b8")


def _replay_timestamp_annotation(fig: go.Figure, replay_timestamp: str) -> None:
    if replay_timestamp:
        fig.add_annotation(
            x=1.0,
            y=1.08,
            xref="paper",
            yref="paper",
            xanchor="right",
            text=f"As of {replay_timestamp}",
            showarrow=False,
            font={"color": "#6c757d"},
        )


def _comparison_axis(frame: pd.DataFrame, normalization_mode: str, spot: float) -> pd.Series:
    strikes = pd.to_numeric(frame.get("strike_price", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    mode = str(normalization_mode).lower()
    if mode == "atm offset":
        atm = estimate_atm_strike(frame, spot=spot)
        return strikes - float(atm or 0.0)
    if mode == "atm %":
        atm = float(estimate_atm_strike(frame, spot=spot) or 0.0)
        return (((strikes / atm) - 1.0) * 100.0) if atm > 0 else strikes * 0.0
    return strikes


def build_oi_profile_figure(df: pd.DataFrame, atm: float = 0.0, max_pain: float = 0.0, selected_strike: float = 0.0) -> go.Figure:
    if df.empty or not {"right", "strike_price", "open_interest"}.issubset(df.columns):
        return _empty_figure("OI Profile", "No option-chain data")
    fig = go.Figure()
    for right, color in (("Call", "#d62728"), ("Put", "#2ca02c")):
        side = df[df["right"] == right].sort_values("strike_price")
        fig.add_trace(
            go.Bar(
                x=side["strike_price"],
                y=side["open_interest"],
                name=f"{right} OI",
                marker_color=color,
            )
        )
    if atm:
        _marker_annotation(fig, atm, "ATM", "#1f77b4")
    if max_pain:
        _marker_annotation(fig, max_pain, "Max Pain", "#9467bd")
    _selected_marker(fig, selected_strike)
    fig.update_layout(title="OI Profile", barmode="group", hovermode="x unified")
    return fig


def build_delta_oi_profile_figure(df: pd.DataFrame, atm: float = 0.0, selected_strike: float = 0.0) -> go.Figure:
    if df.empty or not {"right", "strike_price", "oi_change"}.issubset(df.columns):
        return _empty_figure("Delta OI Profile", "No delta-OI data")
    fig = go.Figure()
    for right, color in (("Call", "#ff9896"), ("Put", "#98df8a")):
        side = df[df["right"] == right].sort_values("strike_price")
        fig.add_trace(go.Bar(x=side["strike_price"], y=side["oi_change"], name=f"{right} ΔOI", marker_color=color))
    if atm:
        _marker_annotation(fig, atm, "ATM", "#1f77b4")
    _selected_marker(fig, selected_strike)
    fig.update_layout(title="Delta OI Profile", barmode="group", hovermode="x unified")
    return fig


def build_replay_delta_oi_figure(
    change_df: pd.DataFrame,
    atm: float = 0.0,
    selected_strike: float = 0.0,
    replay_timestamp: str = "",
    change_window: str = "Since Open",
) -> go.Figure:
    if change_df.empty or not {"strike", "option_type", "open_interest_change"}.issubset(change_df.columns):
        return _empty_figure("Replay Delta/OI Change", "No replay delta/OI change data")
    frame = change_df.copy()
    frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce").fillna(0.0)
    frame["open_interest_change"] = pd.to_numeric(frame["open_interest_change"], errors="coerce").fillna(0.0)
    fig = go.Figure()
    for option_type, label, color in (("CE", "Call ΔOI", "#ff9896"), ("PE", "Put ΔOI", "#98df8a")):
        side = frame[frame["option_type"] == option_type].sort_values("strike")
        fig.add_trace(
            go.Bar(
                x=side["strike"],
                y=side["open_interest_change"],
                name=label,
                marker_color=color,
                customdata=side["strike"],
            )
        )
    if atm:
        _marker_annotation(fig, atm, "ATM", "#1f77b4")
    _selected_marker(fig, selected_strike)
    _replay_timestamp_annotation(fig, replay_timestamp)
    fig.update_layout(
        title=f"Replay Delta/OI Change ({change_window})",
        barmode="group",
        hovermode="x unified",
        yaxis_title="Open Interest Change",
    )
    return fig


def build_iv_smile_figure(df: pd.DataFrame, atm: float = 0.0, selected_expiry: str = "", selected_strike: float = 0.0) -> go.Figure:
    if df.empty or not {"right", "strike_price", "iv"}.issubset(df.columns):
        return _empty_figure("IV Smile", "No IV data")
    fig = go.Figure()
    for right, color in (("Call", "#d62728"), ("Put", "#2ca02c")):
        side = df[df["right"] == right].sort_values("strike_price")
        fig.add_trace(go.Scatter(x=side["strike_price"], y=side["iv"], mode="lines+markers", name=f"{right} IV", line={"color": color}))
    if atm:
        _marker_annotation(fig, atm, "ATM", "#1f77b4")
    _selected_marker(fig, selected_strike)
    title = "IV Smile" if not selected_expiry else f"IV Smile ({selected_expiry})"
    fig.update_layout(title=title, hovermode="x unified")
    return fig


def build_term_structure_figure(expiry_summaries: Iterable[Dict[str, float]]) -> go.Figure:
    summaries = list(expiry_summaries)
    if not summaries:
        return _empty_figure("IV Term Structure", "No expiry summaries")
    fig = go.Figure(
        go.Scatter(
            x=[row["expiry"] for row in summaries],
            y=[row["atm_iv"] * 100 for row in summaries],
            mode="lines+markers",
            name="ATM IV",
        )
    )
    fig.update_layout(title="IV Term Structure", hovermode="x unified", yaxis_title="ATM IV %")
    return fig


def build_multi_expiry_oi_figure(expiry_frames: Dict[str, pd.DataFrame], normalization_mode: str = "absolute", spot: float = 0.0, selected_strike: float = 0.0) -> go.Figure:
    if not expiry_frames:
        return _empty_figure("Multi-Expiry OI", "No expiry data")
    fig = go.Figure()
    added = 0
    for expiry, frame in expiry_frames.items():
        if frame.empty or not {"strike_price", "open_interest", "right"}.issubset(frame.columns):
            continue
        grouped = frame.groupby("strike_price", dropna=True)["open_interest"].sum().reset_index().sort_values("strike_price")
        grouped["comparison_axis"] = _comparison_axis(grouped.rename(columns={"strike_price": "strike_price"}), normalization_mode, spot)
        fig.add_trace(go.Scatter(x=grouped["comparison_axis"], y=grouped["open_interest"], mode="lines+markers", name=expiry, customdata=grouped["strike_price"]))
        added += 1
    if added == 0:
        return _empty_figure("Multi-Expiry OI", "No expiry data")
    fig.update_layout(title="Multi-Expiry OI Overlay", hovermode="x unified", yaxis_title="Open Interest", xaxis_title="Strike" if str(normalization_mode).lower() == "absolute" else normalization_mode)
    _selected_marker(fig, selected_strike if str(normalization_mode).lower() == "absolute" else 0.0)
    return fig


def build_multi_expiry_iv_smile_figure(expiry_frames: Dict[str, pd.DataFrame], normalization_mode: str = "absolute", spot: float = 0.0, selected_strike: float = 0.0) -> go.Figure:
    if not expiry_frames:
        return _empty_figure("Multi-Expiry IV Smile", "No expiry data")
    fig = go.Figure()
    added = 0
    for expiry, frame in expiry_frames.items():
        if frame.empty or not {"strike_price", "iv"}.issubset(frame.columns):
            continue
        grouped = frame.groupby("strike_price", dropna=True)["iv"].mean().reset_index().sort_values("strike_price")
        grouped["comparison_axis"] = _comparison_axis(grouped.rename(columns={"strike_price": "strike_price"}), normalization_mode, spot)
        fig.add_trace(go.Scatter(x=grouped["comparison_axis"], y=grouped["iv"], mode="lines+markers", name=expiry, customdata=grouped["strike_price"]))
        added += 1
    if added == 0:
        return _empty_figure("Multi-Expiry IV Smile", "No expiry data")
    fig.update_layout(title="Multi-Expiry IV Smile", hovermode="x unified", yaxis_title="IV", xaxis_title="Strike" if str(normalization_mode).lower() == "absolute" else normalization_mode)
    _selected_marker(fig, selected_strike if str(normalization_mode).lower() == "absolute" else 0.0)
    return fig


def build_expected_move_figure(expiry_summaries: Iterable[Dict[str, float]], spot: float) -> go.Figure:
    summaries = list(expiry_summaries)
    if not summaries:
        return _empty_figure("Expected Move", "No expiry summaries")
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[row["expiry"] for row in summaries],
            y=[row["expected_move"] for row in summaries],
            name="Expected Move",
            marker_color="#1f77b4",
        )
    )
    if spot > 0:
        fig.add_annotation(
            x=0,
            y=1.05,
            yref="paper",
            text=f"Spot {spot:,.0f}",
            showarrow=False,
        )
    fig.update_layout(title="Expected Move by Expiry", hovermode="x unified")
    return fig


def build_oi_heatmap_figure(snapshot_df: pd.DataFrame, replay_timestamp: str = "") -> go.Figure:
    if snapshot_df.empty or not {"snapshot_ts", "strike", "open_interest"}.issubset(snapshot_df.columns):
        return _empty_figure("OI Heatmap", "No intraday snapshots")
    pivot = snapshot_df.pivot_table(index="strike", columns="snapshot_ts", values="open_interest", aggfunc="sum").sort_index()
    fig = go.Figure(
        go.Heatmap(
            x=list(pivot.columns),
            y=list(pivot.index),
            z=pivot.values,
            colorscale="Viridis",
            colorbar={"title": "OI"},
        )
    )
    if replay_timestamp and replay_timestamp in pivot.columns:
        fig.add_vline(x=replay_timestamp, line_dash="dot", line_color="#17a2b8", opacity=0.9)
    _replay_timestamp_annotation(fig, replay_timestamp)
    fig.update_layout(title="OI Heatmap", hovermode="closest")
    return fig


def build_skew_shift_replay_figure(snapshot_df: pd.DataFrame, replay_timestamp: str = "") -> go.Figure:
    if snapshot_df.empty or not {"snapshot_ts", "option_type", "iv"}.issubset(snapshot_df.columns):
        return _empty_figure("Skew Shift Replay", "No replay snapshots")
    grouped = (
        snapshot_df.groupby(["snapshot_ts", "option_type"], dropna=True)["iv"]
        .mean()
        .unstack(fill_value=0)
        .reset_index()
        .sort_values("snapshot_ts")
    )
    grouped["skew_shift"] = grouped.get("PE", 0) - grouped.get("CE", 0)
    fig = go.Figure(
        go.Scatter(
            x=grouped["snapshot_ts"],
            y=grouped["skew_shift"],
            mode="lines+markers",
            name="PE-CE Skew",
        )
    )
    if replay_timestamp and replay_timestamp in grouped["snapshot_ts"].astype(str).tolist():
        fig.add_vline(x=replay_timestamp, line_dash="dot", line_color="#17a2b8", opacity=0.9)
    _replay_timestamp_annotation(fig, replay_timestamp)
    fig.update_layout(title="Skew Shift Replay", hovermode="x unified", yaxis_title="IV Skew")
    return fig


def build_gamma_exposure_figure(df: pd.DataFrame, walls: Optional[List[Dict[str, float]]] = None, selected_strike: float = 0.0) -> go.Figure:
    if df.empty or not {"strike_price", "net_gamma"}.issubset(df.columns):
        return _empty_figure("Gamma Exposure", "No gamma data")
    ordered = df.sort_values("strike_price")
    fig = go.Figure(go.Bar(x=ordered["strike_price"], y=ordered["net_gamma"], name="Net Gamma"))
    for wall in walls or []:
        _marker_annotation(fig, wall["strike"], "Gamma Wall", "#ff7f0e")
    _selected_marker(fig, selected_strike)
    fig.update_layout(title="Gamma Exposure Profile", hovermode="x unified")
    return fig


def build_vanna_exposure_figure(df: pd.DataFrame, selected_strike: float = 0.0) -> go.Figure:
    if df.empty or not {"strike_price", "net_vanna"}.issubset(df.columns):
        return _empty_figure("Vanna Exposure", "No vanna data")
    ordered = df.sort_values("strike_price")
    fig = go.Figure(go.Bar(x=ordered["strike_price"], y=ordered["net_vanna"], name="Net Vanna", marker_color="#8c564b"))
    _selected_marker(fig, selected_strike)
    fig.update_layout(title="Vanna Exposure Profile", hovermode="x unified")
    return fig


def build_charm_exposure_figure(df: pd.DataFrame, selected_strike: float = 0.0) -> go.Figure:
    if df.empty or not {"strike_price", "net_charm"}.issubset(df.columns):
        return _empty_figure("Charm Exposure", "No charm data")
    ordered = df.sort_values("strike_price")
    fig = go.Figure(go.Bar(x=ordered["strike_price"], y=ordered["net_charm"], name="Net Charm", marker_color="#17becf"))
    _selected_marker(fig, selected_strike)
    fig.update_layout(title="Charm Exposure Profile", hovermode="x unified")
    return fig


def build_liquidity_scatter_figure(df: pd.DataFrame) -> go.Figure:
    if df.empty or not {"spread_pct", "volume", "open_interest", "strike_price"}.issubset(df.columns):
        return _empty_figure("Liquidity Scatter", "No liquidity data")
    fig = go.Figure(
        go.Scatter(
            x=df["spread_pct"],
            y=df["volume"],
            mode="markers",
            text=df["strike_price"],
            marker={"size": (df["open_interest"].fillna(0) / 1000.0).clip(lower=8, upper=30)},
            name="Strikes",
        )
    )
    fig.update_layout(title="Liquidity Scatter", hovermode="closest", xaxis_title="Spread %", yaxis_title="Volume")
    return fig
