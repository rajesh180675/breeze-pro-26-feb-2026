"""
Production-grade Plotly chart generators for Breeze PRO.

All functions return go.Figure objects ready for st.plotly_chart().
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_candlestick(
    df: pd.DataFrame,
    title: str = "",
    show_volume: bool = True,
    show_ema: Optional[List[int]] = None,
    show_bb: bool = False,
    show_vwap: bool = False,
    support_resistance: bool = False,
    height: int = 600,
) -> go.Figure:
    """
    Professional OHLCV candlestick chart with optional overlays and volume subplot.
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=18),
        )
        return fig

    rows = 2 if show_volume else 1
    row_heights = [0.75, 0.25] if show_volume else [1.0]

    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
    )

    colors_up = "#26a69a"
    colors_down = "#ef5350"

    fig.add_trace(
        go.Candlestick(
            x=df["datetime"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color=colors_up,
            decreasing_line_color=colors_down,
            increasing_fillcolor=colors_up,
            decreasing_fillcolor=colors_down,
            line=dict(width=1),
            whiskerwidth=0.8,
            hoverlabel=dict(bgcolor="rgba(0,0,0,0.8)", font_color="white"),
        ),
        row=1,
        col=1,
    )

    if show_ema:
        from ta_indicators import ema as _ema

        ema_colors = ["#FFB300", "#AB47BC", "#26C6DA", "#66BB6A"]
        for idx, period in enumerate(show_ema):
            ema_vals = _ema(df["close"], period)
            fig.add_trace(
                go.Scatter(
                    x=df["datetime"],
                    y=ema_vals,
                    mode="lines",
                    name=f"EMA {period}",
                    line=dict(color=ema_colors[idx % len(ema_colors)], width=1.5, dash="solid"),
                    opacity=0.85,
                    hoverinfo="skip",
                ),
                row=1,
                col=1,
            )

    if show_bb:
        from ta_indicators import bollinger_bands as _bb

        upper, mid, lower = _bb(df["close"])
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=upper,
                name="BB Upper",
                line=dict(color="rgba(100,150,250,0.7)", width=1, dash="dot"),
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=mid,
                name="BB Middle",
                line=dict(color="rgba(100,150,250,0.5)", width=1),
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=lower,
                name="BB Lower",
                line=dict(color="rgba(100,150,250,0.7)", width=1, dash="dot"),
                fill="tonexty",
                fillcolor="rgba(100,150,250,0.05)",
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )

    if show_vwap and "volume" in df.columns:
        from ta_indicators import vwap as _vwap

        vwap_vals = _vwap(df["high"], df["low"], df["close"], df["volume"])
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=vwap_vals,
                name="VWAP",
                line=dict(color="#FF6F00", width=1.5, dash="dashdot"),
                opacity=0.9,
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )

    if support_resistance and len(df) >= 20:
        levels = _detect_support_resistance(df["close"], df["high"], df["low"], n=5)
        for level, label in levels:
            fig.add_hline(
                y=level,
                line_color="rgba(255,200,50,0.6)",
                line_width=1,
                line_dash="dot",
                annotation_text=f"  {label} ₹{level:,.0f}",
                annotation_position="right",
                row=1,
                col=1,
            )

    if show_volume and "volume" in df.columns:
        vol_colors = [colors_up if c >= o else colors_down for c, o in zip(df["close"], df["open"])]
        fig.add_trace(
            go.Bar(
                x=df["datetime"],
                y=df["volume"],
                name="Volume",
                marker_color=vol_colors,
                marker_opacity=0.6,
                showlegend=False,
                hovertemplate="Vol: %{y:,.0f}<extra></extra>",
            ),
            row=2,
            col=1,
        )
        fig.update_yaxes(title_text="Volume", row=2, col=1, showgrid=False)

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#2c3e50")),
        height=height,
        xaxis_rangeslider_visible=False,
        plot_bgcolor="#0d1117",
        paper_bgcolor="#161b22",
        font=dict(color="#e6edf3", size=11),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(22,27,34,0.8)",
        ),
        margin=dict(l=10, r=10, t=50 if title else 10, b=10),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(48,54,61,0.8)",
            rangeslider=dict(visible=True, thickness=0.04),
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1D", step="day", stepmode="backward"),
                    dict(count=5, label="5D", step="day", stepmode="backward"),
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor="#161b22",
                activecolor="#388bfd",
                font=dict(color="#e6edf3"),
            ),
        ),
        yaxis=dict(showgrid=True, gridcolor="rgba(48,54,61,0.8)", side="right"),
    )
    # Task 1.3: IST-aware tick format for chart x-axis labels
    fig.update_xaxes(tickformat="%d %b %H:%M", row=1, col=1)
    return fig


def render_technical_subplot(
    df: pd.DataFrame,
    indicator: str,
    params: Dict = None,
    height: int = 200,
) -> go.Figure:
    """Render a technical indicator in a standalone subplot."""
    from ta_indicators import macd as _macd
    from ta_indicators import rsi as _rsi
    from ta_indicators import stochastic as _stoch

    params = params or {}
    fig = go.Figure()

    if indicator == "rsi":
        period = params.get("period", 14)
        rsi_vals = _rsi(df["close"], period)
        fig.add_trace(go.Scatter(x=df["datetime"], y=rsi_vals, name=f"RSI({period})", line=dict(color="#7B68EE", width=1.5)))
        fig.add_hline(y=70, line_color="rgba(239,83,80,0.5)", line_dash="dash")
        fig.add_hline(y=30, line_color="rgba(38,166,154,0.5)", line_dash="dash")
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(239,83,80,0.05)", line_width=0)
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(38,166,154,0.05)", line_width=0)
        fig.update_yaxes(range=[0, 100], dtick=20)

    elif indicator == "macd":
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal = params.get("signal", 9)
        macd_line, signal_line, histogram = _macd(df["close"], fast, slow, signal)
        hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in histogram.fillna(0)]
        fig.add_trace(go.Bar(x=df["datetime"], y=histogram, name="Histogram", marker_color=hist_colors, opacity=0.7))
        fig.add_trace(go.Scatter(x=df["datetime"], y=macd_line, name=f"MACD({fast},{slow})", line=dict(color="#7B68EE", width=1.5)))
        fig.add_trace(go.Scatter(x=df["datetime"], y=signal_line, name=f"Signal({signal})", line=dict(color="#FF6F00", width=1.5)))
        fig.add_hline(y=0, line_color="rgba(230,237,243,0.3)", line_width=0.5)

    elif indicator == "stochastic":
        k_period = params.get("k_period", 14)
        d_period = params.get("d_period", 3)
        k, d = _stoch(df["high"], df["low"], df["close"], k_period, d_period)
        fig.add_trace(go.Scatter(x=df["datetime"], y=k, name=f"%K({k_period})", line=dict(color="#7B68EE", width=1.5)))
        fig.add_trace(go.Scatter(x=df["datetime"], y=d, name=f"%D({d_period})", line=dict(color="#FF6F00", width=1.5, dash="dot")))
        fig.add_hline(y=80, line_color="rgba(239,83,80,0.5)", line_dash="dash")
        fig.add_hline(y=20, line_color="rgba(38,166,154,0.5)", line_dash="dash")
        fig.update_yaxes(range=[0, 100])

    fig.update_layout(
        height=height,
        plot_bgcolor="#0d1117",
        paper_bgcolor="#161b22",
        font=dict(color="#e6edf3", size=10),
        legend=dict(orientation="h", y=1.05, x=0),
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis=dict(showgrid=True, gridcolor="rgba(48,54,61,0.8)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(48,54,61,0.8)", side="right"),
    )
    return fig


def render_iv_surface(
    expiry_chain_dict: Dict[str, pd.DataFrame],
    spot: float,
    instrument: str = "",
    height: int = 600,
) -> go.Figure:
    """Render a 3D IV Surface."""
    from datetime import datetime as _dt

    x_vals, y_vals, z_vals = [], [], []

    for expiry_str, chain_df in expiry_chain_dict.items():
        if chain_df.empty:
            continue
        try:
            expiry_dt = _dt.strptime(expiry_str[:10], "%Y-%m-%d")
            dte = (expiry_dt - _dt.now()).days
        except Exception:
            continue

        iv_col = "iv_call" if "iv_call" in chain_df.columns else "iv"
        if iv_col not in chain_df.columns:
            continue

        for _, row in chain_df.iterrows():
            strike = row.get("strike", 0)
            iv = row.get(iv_col, 0)
            if not strike or not iv or iv > 300:
                continue
            moneyness = strike / spot * 100
            if 80 <= moneyness <= 120:
                x_vals.append(round(moneyness, 2))
                y_vals.append(dte)
                z_vals.append(round(iv, 2))

    if len(x_vals) < 4:
        fig = go.Figure()
        fig.add_annotation(
            text="Insufficient data for IV surface (need ≥2 expiries with IV)",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14),
        )
        return fig

    fig = go.Figure(
        data=[
            go.Scatter3d(
                x=x_vals,
                y=y_vals,
                z=z_vals,
                mode="markers",
                marker=dict(size=4, color=z_vals, colorscale="Viridis", colorbar=dict(title="IV %"), opacity=0.85),
                hovertemplate="Moneyness: %{x:.1f}%<br>DTE: %{y}d<br>IV: %{z:.1f}%<extra></extra>",
            )
        ]
    )

    fig.add_trace(
        go.Scatter3d(
            x=[100, 100],
            y=[min(y_vals), max(y_vals)],
            z=[min(z_vals), min(z_vals)],
            mode="lines",
            line=dict(color="white", width=3),
            name="ATM",
            showlegend=True,
        )
    )

    fig.update_layout(
        title=f"{instrument} IV Surface — Spot: ₹{spot:,.0f}",
        scene=dict(
            xaxis_title="Moneyness (%)",
            yaxis_title="DTE (days)",
            zaxis_title="IV (%)",
            bgcolor="#0d1117",
            xaxis=dict(gridcolor="rgba(48,54,61,0.8)"),
            yaxis=dict(gridcolor="rgba(48,54,61,0.8)"),
            zaxis=dict(gridcolor="rgba(48,54,61,0.8)"),
        ),
        height=height,
        paper_bgcolor="#161b22",
        font=dict(color="#e6edf3"),
        margin=dict(l=0, r=0, t=50, b=0),
    )
    return fig


def _detect_support_resistance(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    n: int = 5,
    window: int = 10,
) -> List[Tuple[float, str]]:
    """Simple swing high/low detection for support/resistance levels."""
    levels = []
    for i in range(window, len(close) - window):
        if high.iloc[i] == high.iloc[i - window : i + window].max():
            levels.append((round(high.iloc[i], 2), "R"))
        if low.iloc[i] == low.iloc[i - window : i + window].min():
            levels.append((round(low.iloc[i], 2), "S"))

    if not levels:
        return []

    levels.sort(key=lambda x: x[0])
    clustered = [levels[0]]
    for level, ltype in levels[1:]:
        if abs(level - clustered[-1][0]) / clustered[-1][0] > 0.005:
            clustered.append((level, ltype))

    return clustered[-n:]
