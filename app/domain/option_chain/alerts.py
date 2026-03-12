"""Deterministic option-chain alerts and commentary."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .metrics import calculate_max_pain, detect_gamma_walls, normalize_iv


def _wall_strike(df: pd.DataFrame, right: str) -> Optional[int]:
    if df.empty or not {"right", "strike_price", "open_interest"}.issubset(df.columns):
        return None
    side = df[df["right"] == right]
    if side.empty:
        return None
    idx = side["open_interest"].astype(float).idxmax()
    return int(float(side.loc[idx, "strike_price"]))


def _atm_iv(df: pd.DataFrame, spot: float) -> float:
    if df.empty or not {"strike_price", "iv"}.issubset(df.columns):
        return 0.0
    strikes = sorted(pd.to_numeric(df["strike_price"], errors="coerce").dropna().unique())
    if not strikes:
        return 0.0
    atm = min(strikes, key=lambda strike: abs(strike - spot)) if spot > 0 else strikes[len(strikes) // 2]
    atm_rows = df[df["strike_price"] == atm]
    ivs = pd.to_numeric(atm_rows["iv"], errors="coerce").dropna()
    if ivs.empty:
        return 0.0
    normalized = [normalize_iv(v) for v in ivs]
    return float(sum(normalized) / len(normalized))


def _skew_value(df: pd.DataFrame, spot: float) -> float:
    if df.empty or not {"right", "strike_price", "iv"}.issubset(df.columns):
        return 0.0
    strikes = sorted(pd.to_numeric(df["strike_price"], errors="coerce").dropna().unique())
    if len(strikes) < 3:
        return 0.0
    atm = min(strikes, key=lambda strike: abs(strike - spot)) if spot > 0 else strikes[len(strikes) // 2]
    put_strike = min(strikes, key=lambda strike: abs(strike - (atm - 100)))
    call_strike = min(strikes, key=lambda strike: abs(strike - (atm + 100)))
    put_iv = pd.to_numeric(df[(df["right"] == "Put") & (df["strike_price"] == put_strike)]["iv"], errors="coerce").dropna()
    call_iv = pd.to_numeric(df[(df["right"] == "Call") & (df["strike_price"] == call_strike)]["iv"], errors="coerce").dropna()
    if put_iv.empty or call_iv.empty:
        return 0.0
    return float(normalize_iv(put_iv.iloc[0]) - normalize_iv(call_iv.iloc[0]))


def evaluate_alerts(
    current_df: pd.DataFrame,
    previous_df: Optional[pd.DataFrame] = None,
    spot: float = 0.0,
    expiry: str = "",
    monitored_strikes: Optional[List[int]] = None,
    snapshot_ts: str = "",
) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    call_wall = _wall_strike(current_df, "Call")
    put_wall = _wall_strike(current_df, "Put")
    if previous_df is not None and not previous_df.empty:
        prev_call_wall = _wall_strike(previous_df, "Call")
        prev_put_wall = _wall_strike(previous_df, "Put")
        if call_wall and prev_call_wall and call_wall != prev_call_wall:
            alerts.append(
                {
                    "code": "call_wall_shift",
                    "severity": "medium",
                    "strike": call_wall,
                    "expiry": expiry,
                    "cause": "open_interest_peak_shift",
                    "timestamp": snapshot_ts,
                    "message": f"Call wall shifted from {prev_call_wall} to {call_wall}.",
                }
            )
        if put_wall and prev_put_wall and put_wall != prev_put_wall:
            alerts.append(
                {
                    "code": "put_wall_shift",
                    "severity": "medium",
                    "strike": put_wall,
                    "expiry": expiry,
                    "cause": "open_interest_peak_shift",
                    "timestamp": snapshot_ts,
                    "message": f"Put wall shifted from {prev_put_wall} to {put_wall}.",
                }
            )
        current_atm_iv = _atm_iv(current_df, spot)
        previous_atm_iv = _atm_iv(previous_df, spot)
        if current_atm_iv - previous_atm_iv >= 0.02:
            alerts.append(
                {
                    "code": "atm_iv_jump",
                    "severity": "high",
                    "expiry": expiry,
                    "cause": "atm_iv_change",
                    "timestamp": snapshot_ts,
                    "message": f"ATM IV jumped by {(current_atm_iv - previous_atm_iv) * 100:.1f} vol points.",
                }
            )
        current_skew = _skew_value(current_df, spot)
        previous_skew = _skew_value(previous_df, spot)
        if current_skew - previous_skew >= 0.01:
            alerts.append(
                {
                    "code": "skew_steepening",
                    "severity": "medium",
                    "expiry": expiry,
                    "cause": "put_call_skew_change",
                    "timestamp": snapshot_ts,
                    "message": f"Put-call skew steepened by {(current_skew - previous_skew) * 100:.1f} vol points.",
                }
            )
    if not current_df.empty and "spread_pct" in current_df.columns:
        blowout = current_df[pd.to_numeric(current_df["spread_pct"], errors="coerce") >= 5]
        if not blowout.empty:
            row = blowout.sort_values("spread_pct", ascending=False).iloc[0]
            alerts.append(
                {
                    "code": "spread_blowout",
                    "severity": "medium",
                    "strike": int(float(row["strike_price"])),
                    "expiry": expiry,
                    "cause": "wide_bid_ask_spread",
                    "timestamp": snapshot_ts,
                    "message": f"Spread blowout at {int(float(row['strike_price']))} with {float(row['spread_pct']):.1f}% spread.",
                }
            )
    if not current_df.empty and {"volume", "avg_volume"}.issubset(current_df.columns):
        unusual = current_df[pd.to_numeric(current_df["volume"], errors="coerce") > (pd.to_numeric(current_df["avg_volume"], errors="coerce").fillna(0) * 3)]
        if monitored_strikes:
            pinned_unusual = unusual[unusual["strike_price"].isin(monitored_strikes)]
            if not pinned_unusual.empty:
                row = pinned_unusual.sort_values("volume", ascending=False).iloc[0]
                alerts.append(
                    {
                        "code": "pinned_strike_volume",
                        "severity": "medium",
                        "strike": int(float(row["strike_price"])),
                        "expiry": expiry,
                        "cause": "pinned_strike_volume_vs_baseline",
                        "timestamp": snapshot_ts,
                        "message": f"Pinned strike {int(float(row['strike_price']))} is trading unusual volume.",
                    }
                )
            unusual = pinned_unusual
        if not unusual.empty:
            row = unusual.sort_values("volume", ascending=False).iloc[0]
            alerts.append(
                {
                    "code": "unusual_volume",
                    "severity": "low",
                    "strike": int(float(row["strike_price"])),
                    "expiry": expiry,
                    "cause": "volume_vs_baseline",
                    "timestamp": snapshot_ts,
                    "message": f"Unusual volume at {int(float(row['strike_price']))}.",
                }
            )
    return alerts


def build_commentary(
    current_df: pd.DataFrame,
    alerts: List[Dict[str, Any]],
    spot: float = 0.0,
    expiry: str = "",
) -> List[str]:
    commentary: List[str] = []
    call_wall = _wall_strike(current_df, "Call")
    put_wall = _wall_strike(current_df, "Put")
    max_pain = calculate_max_pain(current_df)
    if put_wall:
        commentary.append(f"Put writing strongest at {put_wall}; support is concentrated there.")
    if call_wall:
        commentary.append(f"Call OI concentrated at {call_wall}; resistance is defined there.")
    if max_pain:
        commentary.append(f"Max pain is parked near {max_pain} for {expiry or 'the active expiry'}.")
    gamma_walls = detect_gamma_walls(current_df, top_n=1)
    if gamma_walls:
        commentary.append(f"Gamma wall candidate at {int(gamma_walls[0]['strike'])}.")
    for alert in alerts[:2]:
        commentary.append(alert["message"])
    if not commentary and spot > 0:
        commentary.append(f"Option chain is stable around spot {spot:,.0f}.")
    return commentary
