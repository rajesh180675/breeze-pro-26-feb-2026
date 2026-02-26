"""
Technical analysis indicators implemented from scratch.
No TA-Lib dependency. Uses only pandas and numpy.

All functions accept pd.Series and return pd.Series or Tuples of pd.Series.
NaN values are produced for the warm-up period.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.
    Uses pandas ewm with adjust=False (standard EMA).
    """
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's RSI (Relative Strength Index).
    Returns series in range [0, 100]. First `period` values are NaN.

    Algorithm:
      1. Compute daily price changes (delta)
      2. Separate gains (positive deltas) and losses (absolute negative deltas)
      3. Initial average gain/loss = simple average of first `period` values
      4. Subsequent: RS_avg = (prev_avg × (period-1) + current) / period (Wilder smoothing)
      5. RSI = 100 - (100 / (1 + RS_avg_gain / RS_avg_loss))
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_values = 100 - (100 / (1 + rs))
    rsi_values.iloc[:period] = np.nan
    return rsi_values.rename("rsi")


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD (Moving Average Convergence/Divergence).

    Returns:
      (macd_line, signal_line, histogram)

    macd_line  = EMA(close, fast) - EMA(close, slow)
    signal_line = EMA(macd_line, signal)
    histogram  = macd_line - signal_line
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = (ema_fast - ema_slow).rename("macd")
    signal_line = ema(macd_line, signal).rename("signal")
    histogram = (macd_line - signal_line).rename("histogram")
    return macd_line, signal_line, histogram


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    Returns:
      (upper_band, middle_band, lower_band)

    middle_band = SMA(close, period)
    upper_band  = middle_band + std_dev × σ(close, period)
    lower_band  = middle_band - std_dev × σ(close, period)

    where σ is the rolling population standard deviation.
    """
    middle = sma(close, period).rename("bb_mid")
    std = close.rolling(window=period).std(ddof=0)
    upper = (middle + std_dev * std).rename("bb_upper")
    lower = (middle - std_dev * std).rename("bb_lower")
    return upper, middle, lower


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Average True Range.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = Wilder's smoothing of True Range over `period` bars.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean().rename("atr")


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    Volume-Weighted Average Price.

    VWAP = cumsum(typical_price × volume) / cumsum(volume)
    typical_price = (high + low + close) / 3

    Note: This implementation computes VWAP cumulatively over the entire series.
    For a proper session-reset VWAP, reset the series at each market open
    before calling this function.
    """
    typical_price = (high + low + close) / 3
    cumulative_tpv = (typical_price * volume).cumsum()
    cumulative_vol = volume.cumsum().replace(0, np.nan)
    return (cumulative_tpv / cumulative_vol).rename("vwap")


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> Tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator.

    %K = (close - lowest_low_N) / (highest_high_N - lowest_low_N) × 100
    %D = SMA(%K, d_period)

    Returns:
      (%K, %D) — both in range [0, 100]
    """
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    k = ((close - lowest_low) / denom * 100).rename("stoch_k")
    d = sma(k, d_period).rename("stoch_d")
    return k, d


def pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
    """
    Standard pivot points based on previous period's OHLCV.

    Returns:
      {P, R1, R2, R3, S1, S2, S3}

    Formulas:
      P  = (high + low + close) / 3
      R1 = 2×P - low
      R2 = P + (high - low)
      R3 = high + 2×(P - low)
      S1 = 2×P - high
      S2 = P - (high - low)
      S3 = low - 2×(high - P)
    """
    p = (high + low + close) / 3.0
    return {
        "P": round(p, 2),
        "R1": round(2 * p - low, 2),
        "R2": round(p + (high - low), 2),
        "R3": round(high + 2 * (p - low), 2),
        "S1": round(2 * p - high, 2),
        "S2": round(p - (high - low), 2),
        "S3": round(low - 2 * (high - p), 2),
    }


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> Tuple[pd.Series, pd.Series]:
    """
    Supertrend indicator.
    Returns (supertrend_line, direction) where direction: 1=bullish, -1=bearish.
    """
    atr_series = atr(high, low, close, period)
    hl_avg = (high + low) / 2
    upper_band = hl_avg + multiplier * atr_series
    lower_band = hl_avg - multiplier * atr_series

    st = pd.Series(index=close.index, dtype=float)
    direction = pd.Series(index=close.index, dtype=int)

    for i in range(1, len(close)):
        if pd.isna(atr_series.iloc[i]):
            st.iloc[i] = np.nan
            direction.iloc[i] = 1
            continue

        prev_st = st.iloc[i - 1] if not pd.isna(st.iloc[i - 1]) else upper_band.iloc[i]
        prev_dir = direction.iloc[i - 1] if not pd.isna(direction.iloc[i - 1]) else 1

        if prev_dir == 1:
            if close.iloc[i] < lower_band.iloc[i]:
                direction.iloc[i] = -1
                st.iloc[i] = upper_band.iloc[i]
            else:
                direction.iloc[i] = 1
                st.iloc[i] = max(lower_band.iloc[i], prev_st)
        else:
            if close.iloc[i] > upper_band.iloc[i]:
                direction.iloc[i] = 1
                st.iloc[i] = lower_band.iloc[i]
            else:
                direction.iloc[i] = -1
                st.iloc[i] = min(upper_band.iloc[i], prev_st)

    return st.rename("supertrend"), direction.rename("st_direction")


def iv_rank(
    current_iv: float,
    historical_ivs: List[float],
) -> float:
    """
    IV Rank = (current_iv - 52w_low_iv) / (52w_high_iv - 52w_low_iv) × 100

    Returns value in range [0, 100].
    Higher value = IV is relatively high (favorable for premium selling).
    Returns 50.0 if insufficient history.
    """
    if len(historical_ivs) < 10:
        return 50.0
    min_iv = min(historical_ivs)
    max_iv = max(historical_ivs)
    if max_iv - min_iv < 0.001:
        return 50.0
    rank = (current_iv - min_iv) / (max_iv - min_iv) * 100
    return round(max(0.0, min(100.0, rank)), 1)


def iv_percentile(
    current_iv: float,
    historical_ivs: List[float],
) -> float:
    """
    IV Percentile = fraction of historical observations BELOW current_iv × 100.
    More statistically meaningful than IV Rank for skewed IV distributions.
    Returns value in range [0, 100].
    """
    if not historical_ivs:
        return 50.0
    count_below = sum(1 for iv in historical_ivs if iv < current_iv)
    return round(count_below / len(historical_ivs) * 100, 1)
