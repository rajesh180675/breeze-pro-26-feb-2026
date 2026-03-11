"""Deterministic analytics for the option-chain workspace."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

import app_config as C
from analytics import calculate_greeks


def _as_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return default
    return float(numeric) if pd.notna(numeric) else default


def normalize_iv(value: Any) -> float:
    iv = _as_float(value, 0.0)
    return iv / 100.0 if iv > 1 else iv


def _time_to_expiry_years(expiry: str) -> float:
    try:
        expiry_dt = datetime.strptime(str(expiry)[:10], "%Y-%m-%d")
        return max((expiry_dt - datetime.now()).days / C.DAYS_PER_YEAR, 1 / C.DAYS_PER_YEAR)
    except Exception:
        return 7 / C.DAYS_PER_YEAR


def calculate_pcr(df: pd.DataFrame) -> float:
    if df.empty or "right" not in df.columns or "open_interest" not in df.columns:
        return 0.0
    calls = _as_numeric_series(df.loc[df["right"] == "Call", "open_interest"]).sum()
    puts = _as_numeric_series(df.loc[df["right"] == "Put", "open_interest"]).sum()
    return float(puts / calls) if calls > 0 else 0.0


def calculate_max_pain(df: pd.DataFrame) -> int:
    if df.empty or not {"strike_price", "right", "open_interest"}.issubset(df.columns):
        return 0
    strikes = sorted(_as_numeric_series(df["strike_price"]).dropna().unique())
    if not strikes:
        return 0
    pain_by_strike: Dict[float, float] = {}
    for settlement in strikes:
        call_loss = (
            (settlement - df[(df["right"] == "Call") & (df["strike_price"] < settlement)]["strike_price"])
            * df[(df["right"] == "Call") & (df["strike_price"] < settlement)]["open_interest"]
        ).sum()
        put_loss = (
            (df[(df["right"] == "Put") & (df["strike_price"] > settlement)]["strike_price"] - settlement)
            * df[(df["right"] == "Put") & (df["strike_price"] > settlement)]["open_interest"]
        ).sum()
        pain_by_strike[settlement] = float(call_loss + put_loss)
    return int(min(pain_by_strike, key=pain_by_strike.get)) if pain_by_strike else 0


def calculate_iv_percentile(current_iv: float, history: Iterable[float]) -> float:
    cur = normalize_iv(current_iv)
    values = [normalize_iv(v) for v in history if normalize_iv(v) > 0]
    if cur <= 0 or not values:
        return 0.0
    below = sum(1 for value in values if value <= cur)
    return round((below / len(values)) * 100.0, 1)


def calculate_iv_zscore(current_iv: float, history: Iterable[float]) -> float:
    cur = normalize_iv(current_iv)
    values = [normalize_iv(v) for v in history if normalize_iv(v) > 0]
    if cur <= 0 or len(values) < 2:
        return 0.0
    std = float(np.std(values, ddof=0))
    if std == 0:
        return 0.0
    mean = float(np.mean(values))
    return round((cur - mean) / std, 4)


def classify_oi_buildup(ltp_change: float, oi_change: float) -> str:
    if ltp_change > 0 and oi_change > 0:
        return "Long Build-up"
    if ltp_change < 0 and oi_change > 0:
        return "Short Build-up"
    if ltp_change > 0 and oi_change < 0:
        return "Short Covering"
    if ltp_change < 0 and oi_change < 0:
        return "Long Unwinding"
    return "Neutral"


def calculate_liquidity_score(row: Dict[str, Any], freshness_seconds: Optional[float] = None) -> float:
    bid = _as_float(row.get("best_bid_price", row.get("bid", 0)), 0.0)
    ask = _as_float(row.get("best_offer_price", row.get("ask", 0)), 0.0)
    bid_qty = _as_float(row.get("bid_qty", 0), 0.0)
    ask_qty = _as_float(row.get("offer_qty", row.get("ask_qty", 0)), 0.0)
    volume = _as_float(row.get("volume", 0), 0.0)
    oi = _as_float(row.get("open_interest", 0), 0.0)
    mid = ((bid + ask) / 2.0) if bid > 0 and ask > 0 else max(_as_float(row.get("ltp", 0), 0.0), 0.0)
    spread_pct = ((ask - bid) / mid * 100.0) if mid > 0 and ask >= bid and bid > 0 else 100.0
    qty_score = min((bid_qty + ask_qty) / 1000.0, 1.0)
    volume_score = min(volume / 5000.0, 1.0)
    oi_score = min(oi / 100000.0, 1.0)
    spread_score = max(0.0, 1.0 - min(spread_pct / 5.0, 1.0))
    freshness_penalty = 0.0
    if freshness_seconds is not None:
        freshness_penalty = min(max(freshness_seconds, 0.0) / 120.0, 0.5)
    score = (spread_score * 0.4) + (qty_score * 0.2) + (volume_score * 0.2) + (oi_score * 0.2)
    return round(max(0.0, min(score - freshness_penalty, 1.0)) * 100.0, 2)


def calculate_expected_move(
    df: pd.DataFrame,
    spot: float,
    atm_strike: Optional[float] = None,
    days_to_expiry: int = 1,
) -> Dict[str, float]:
    if df.empty:
        return {"straddle": 0.0, "iv_move": 0.0, "expected_move": 0.0}
    atm = float(atm_strike or 0)
    if atm <= 0 and "strike_price" in df.columns and not df["strike_price"].empty:
        strikes = sorted(_as_numeric_series(df["strike_price"]).dropna().unique())
        if strikes:
            atm = min(strikes, key=lambda strike: abs(strike - spot if spot > 0 else strike))
    straddle = 0.0
    if atm > 0 and {"strike_price", "right", "ltp"}.issubset(df.columns):
        call_rows = df[(df["strike_price"] == atm) & (df["right"] == "Call")]
        put_rows = df[(df["strike_price"] == atm) & (df["right"] == "Put")]
        if not call_rows.empty and not put_rows.empty:
            straddle = float(_as_numeric_series(call_rows["ltp"]).iloc[0] + _as_numeric_series(put_rows["ltp"]).iloc[0])
    iv_move = 0.0
    if spot > 0 and "iv" in df.columns:
        iv_values = df[df["strike_price"] == atm]["iv"] if atm > 0 else df["iv"]
        iv_series = _as_numeric_series(iv_values).dropna().map(normalize_iv)
        if not iv_series.empty:
            iv_move = float(spot * iv_series.mean() * math.sqrt(max(days_to_expiry, 1) / 365.0))
    expected_move = straddle if straddle > 0 else iv_move
    return {
        "straddle": round(straddle, 2),
        "iv_move": round(iv_move, 2),
        "expected_move": round(expected_move, 2),
    }


def detect_gamma_walls(df: pd.DataFrame, top_n: int = 2) -> List[Dict[str, float]]:
    if df.empty or not {"strike_price", "gamma", "open_interest"}.issubset(df.columns):
        return []
    working = df.copy()
    working["gamma"] = _as_numeric_series(working["gamma"]).fillna(0.0)
    working["open_interest"] = _as_numeric_series(working["open_interest"]).fillna(0.0)
    if "right" in working.columns:
        working["signed_gamma"] = np.where(
            working["right"].eq("Put"),
            -working["gamma"] * working["open_interest"],
            working["gamma"] * working["open_interest"],
        )
    else:
        working["signed_gamma"] = working["gamma"] * working["open_interest"]
    grouped = (
        working.groupby("strike_price", dropna=True)["signed_gamma"]
        .sum()
        .sort_values(key=lambda s: s.abs(), ascending=False)
        .head(top_n)
    )
    return [
        {"strike": float(strike), "net_gamma": round(float(net_gamma), 4)}
        for strike, net_gamma in grouped.items()
    ]


def calculate_vanna(
    spot: float,
    strike: float,
    expiry: str,
    option_type: str,
    iv: float,
    vol_bump: float = 0.01,
) -> float:
    vol = normalize_iv(iv)
    tte = _time_to_expiry_years(expiry)
    if spot <= 0 or strike <= 0 or vol <= 0 or vol_bump <= 0:
        return 0.0
    up = calculate_greeks(spot, strike, tte, min(vol + vol_bump, 5.0), option_type)["delta"]
    down = calculate_greeks(spot, strike, tte, max(vol - vol_bump, 0.001), option_type)["delta"]
    return round((float(up) - float(down)) / (2.0 * vol_bump), 6)


def calculate_charm(
    spot: float,
    strike: float,
    expiry: str,
    option_type: str,
    iv: float,
    day_bump: int = 1,
) -> float:
    vol = normalize_iv(iv)
    tte = _time_to_expiry_years(expiry)
    if spot <= 0 or strike <= 0 or vol <= 0 or tte <= 0:
        return 0.0
    current_delta = calculate_greeks(spot, strike, tte, vol, option_type)["delta"]
    next_delta = calculate_greeks(spot, strike, max(tte - (day_bump / C.DAYS_PER_YEAR), 1e-6), vol, option_type)["delta"]
    return round(float(next_delta) - float(current_delta), 6)


def build_expiry_summary(df: pd.DataFrame, spot: float, days_to_expiry: int) -> Dict[str, float]:
    if df.empty:
        return {
            "atm_iv": 0.0,
            "pcr": 0.0,
            "call_oi": 0.0,
            "put_oi": 0.0,
            "expected_move": 0.0,
        }
    strikes = sorted(_as_numeric_series(df["strike_price"]).dropna().unique()) if "strike_price" in df.columns else []
    atm = min(strikes, key=lambda strike: abs(strike - spot)) if strikes and spot > 0 else (strikes[len(strikes) // 2] if strikes else 0.0)
    atm_rows = df[df["strike_price"] == atm] if atm else pd.DataFrame()
    atm_iv_values = _as_numeric_series(atm_rows.get("iv", pd.Series(dtype=float))).dropna().map(normalize_iv)
    summary = calculate_expected_move(df, spot=spot, atm_strike=atm, days_to_expiry=days_to_expiry)
    return {
        "atm_iv": round(float(atm_iv_values.mean()) if not atm_iv_values.empty else 0.0, 4),
        "pcr": round(calculate_pcr(df), 4),
        "call_oi": float(_as_numeric_series(df.loc[df["right"] == "Call", "open_interest"]).sum()),
        "put_oi": float(_as_numeric_series(df.loc[df["right"] == "Put", "open_interest"]).sum()),
        "expected_move": float(summary["expected_move"]),
    }


def detect_event_premium(front_atm_iv: float, next_atm_iv: float, threshold: float = 0.03) -> Dict[str, Any]:
    front = normalize_iv(front_atm_iv)
    nxt = normalize_iv(next_atm_iv)
    distortion = round(front - nxt, 4)
    return {
        "distortion": distortion,
        "is_elevated": distortion >= threshold,
    }
