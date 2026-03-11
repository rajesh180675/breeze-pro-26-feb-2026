import pytest

plotly = pytest.importorskip("plotly")

import pandas as pd
import charts

from charts import (
    _detect_support_resistance,
    render_candlestick,
    render_iv_surface,
    render_technical_subplot,
)


def _sample_ohlcv(n: int = 40) -> pd.DataFrame:
    dt = pd.date_range("2026-01-01", periods=n, freq="D")
    base = pd.Series(range(100, 100 + n), dtype=float)
    return pd.DataFrame(
        {
            "datetime": dt,
            "open": base,
            "high": base + 2,
            "low": base - 2,
            "close": base + 1,
            "volume": pd.Series([1000 + i * 10 for i in range(n)], dtype=float),
        }
    )


def test_render_candlestick_empty():
    fig = render_candlestick(pd.DataFrame())
    assert len(fig.data) == 0
    assert fig.layout.annotations[0].text == "No data available"


def test_render_candlestick_full_options():
    df = _sample_ohlcv(50)
    fig = render_candlestick(
        df,
        title="Test",
        show_volume=True,
        show_ema=[20, 50],
        show_bb=True,
        show_vwap=True,
        support_resistance=True,
    )
    assert len(fig.data) >= 1
    names = [trace.name for trace in fig.data]
    assert "Price" in names
    assert "Volume" in names
    assert fig.layout.hovermode == "x unified"
    assert fig.layout.xaxis.showspikes is True
    assert "Last Close" in fig.layout.title.text


def test_render_technical_subplots():
    df = _sample_ohlcv(60)
    for indicator in ["rsi", "macd", "stochastic"]:
        fig = render_technical_subplot(df, indicator)
        assert len(fig.data) >= 1


def test_render_iv_surface_insufficient_and_sufficient():
    empty = {"2026-03-27": pd.DataFrame()}
    fig_empty = render_iv_surface(empty, spot=22000, instrument="NIFTY")
    assert len(fig_empty.data) == 0
    assert "Insufficient data" in fig_empty.layout.annotations[0].text

    df = pd.DataFrame({"strike": [20000, 21000, 22000, 23000], "iv": [10, 12, 14, 13]})
    surface = {
        "2026-03-27": df,
        "2026-04-24": df,
    }
    fig = render_iv_surface(surface, spot=22000, instrument="NIFTY")
    assert len(fig.data) >= 2  # scatter + ATM line


def test_detect_support_resistance_runs():
    df = _sample_ohlcv(60)
    levels = _detect_support_resistance(df["close"], df["high"], df["low"], n=3, window=5)
    assert isinstance(levels, list)


def test_option_chain_chart_builders_do_not_live_in_charts_module():
    forbidden = [
        "build_oi_profile_figure",
        "build_delta_oi_profile_figure",
        "build_iv_smile_figure",
        "build_multi_expiry_oi_figure",
        "build_multi_expiry_iv_smile_figure",
        "build_gamma_exposure_figure",
    ]
    for name in forbidden:
        assert not hasattr(charts, name)
