"""Plotly charts for the option-chain workspace."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import pandas as pd
import plotly.graph_objects as go


def _empty_figure(title: str, message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(title=title, annotations=[{"text": message, "showarrow": False}], hovermode="x unified")
    return fig


def _marker_annotation(fig: go.Figure, x: float, text: str, color: str) -> None:
    fig.add_vline(x=x, line_dash="dot", line_color=color, opacity=0.8)
    fig.add_annotation(x=x, y=1.02, yref="paper", text=text, showarrow=False, font={"color": color})


def build_oi_profile_figure(df: pd.DataFrame, atm: float = 0.0, max_pain: float = 0.0) -> go.Figure:
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
    fig.update_layout(title="OI Profile", barmode="group", hovermode="x unified")
    return fig


def build_delta_oi_profile_figure(df: pd.DataFrame, atm: float = 0.0) -> go.Figure:
    if df.empty or not {"right", "strike_price", "oi_change"}.issubset(df.columns):
        return _empty_figure("Delta OI Profile", "No delta-OI data")
    fig = go.Figure()
    for right, color in (("Call", "#ff9896"), ("Put", "#98df8a")):
        side = df[df["right"] == right].sort_values("strike_price")
        fig.add_trace(go.Bar(x=side["strike_price"], y=side["oi_change"], name=f"{right} ΔOI", marker_color=color))
    if atm:
        _marker_annotation(fig, atm, "ATM", "#1f77b4")
    fig.update_layout(title="Delta OI Profile", barmode="group", hovermode="x unified")
    return fig


def build_iv_smile_figure(df: pd.DataFrame, atm: float = 0.0, selected_expiry: str = "") -> go.Figure:
    if df.empty or not {"right", "strike_price", "iv"}.issubset(df.columns):
        return _empty_figure("IV Smile", "No IV data")
    fig = go.Figure()
    for right, color in (("Call", "#d62728"), ("Put", "#2ca02c")):
        side = df[df["right"] == right].sort_values("strike_price")
        fig.add_trace(go.Scatter(x=side["strike_price"], y=side["iv"], mode="lines+markers", name=f"{right} IV", line={"color": color}))
    if atm:
        _marker_annotation(fig, atm, "ATM", "#1f77b4")
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


def build_oi_heatmap_figure(snapshot_df: pd.DataFrame) -> go.Figure:
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
    fig.update_layout(title="OI Heatmap", hovermode="closest")
    return fig


def build_gamma_exposure_figure(df: pd.DataFrame, walls: Optional[List[Dict[str, float]]] = None) -> go.Figure:
    if df.empty or not {"strike_price", "net_gamma"}.issubset(df.columns):
        return _empty_figure("Gamma Exposure", "No gamma data")
    ordered = df.sort_values("strike_price")
    fig = go.Figure(go.Bar(x=ordered["strike_price"], y=ordered["net_gamma"], name="Net Gamma"))
    for wall in walls or []:
        _marker_annotation(fig, wall["strike"], "Gamma Wall", "#ff7f0e")
    fig.update_layout(title="Gamma Exposure Profile", hovermode="x unified")
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
