import numpy as np
import pandas as pd

from ta_indicators import (
    atr,
    bollinger_bands,
    ema,
    iv_percentile,
    iv_rank,
    macd,
    pivot_points,
    rsi,
    sma,
    stochastic,
    supertrend,
    vwap,
)


def test_moving_averages_basic_shapes():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert len(ema(s, 3)) == 5
    sma_vals = sma(s, 3)
    assert np.isnan(sma_vals.iloc[0])
    assert sma_vals.iloc[-1] == 4.0


def test_rsi_has_warmup_nans_and_name():
    close = pd.Series(np.linspace(100, 120, 30))
    out = rsi(close, period=14)
    assert out.name == "rsi"
    assert out.iloc[:14].isna().all()


def test_macd_and_bollinger_names():
    close = pd.Series(np.linspace(100, 130, 40))
    m, sig, hist = macd(close)
    assert m.name == "macd"
    assert sig.name == "signal"
    assert hist.name == "histogram"

    up, mid, low = bollinger_bands(close)
    assert up.name == "bb_upper"
    assert mid.name == "bb_mid"
    assert low.name == "bb_lower"


def test_atr_vwap_stochastic_supertrend_run():
    high = pd.Series([101, 103, 104, 106, 105, 108, 110], dtype=float)
    low = pd.Series([99, 100, 102, 103, 102, 104, 106], dtype=float)
    close = pd.Series([100, 102, 103, 104, 103, 107, 109], dtype=float)
    vol = pd.Series([10, 12, 14, 13, 11, 15, 17], dtype=float)

    atr_out = atr(high, low, close, period=3)
    assert atr_out.name == "atr"

    vwap_out = vwap(high, low, close, vol)
    assert vwap_out.name == "vwap"
    assert vwap_out.notna().all()

    k, d = stochastic(high, low, close, k_period=3, d_period=2)
    assert k.name == "stoch_k"
    assert d.name == "stoch_d"

    st_line, st_dir = supertrend(high, low, close, period=3, multiplier=2.0)
    assert st_line.name == "supertrend"
    assert st_dir.name == "st_direction"


def test_pivot_iv_rank_iv_percentile_values():
    piv = pivot_points(high=120.0, low=100.0, close=110.0)
    assert piv["P"] == 110.0
    assert piv["R1"] == 120.0
    assert piv["S1"] == 100.0

    hist = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28]
    assert iv_rank(20, hist) == 55.6
    assert iv_percentile(20, hist) == 50.0
