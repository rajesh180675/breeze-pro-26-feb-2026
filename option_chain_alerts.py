"""Deterministic option-chain alerts and commentary."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from option_chain_metrics import calculate_max_pain, detect_gamma_walls, normalize_iv


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


def evaluate_alerts(
    current_df: pd.DataFrame,
    previous_df: Optional[pd.DataFrame] = None,
    spot: float = 0.0,
    expiry: str = "",
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
                    "message": f"ATM IV jumped by {(current_atm_iv - previous_atm_iv) * 100:.1f} vol points.",
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
                    "message": f"Spread blowout at {int(float(row['strike_price']))} with {float(row['spread_pct']):.1f}% spread.",
                }
            )
    if not current_df.empty and {"volume", "avg_volume"}.issubset(current_df.columns):
        unusual = current_df[pd.to_numeric(current_df["volume"], errors="coerce") > (pd.to_numeric(current_df["avg_volume"], errors="coerce").fillna(0) * 3)]
        if not unusual.empty:
            row = unusual.sort_values("volume", ascending=False).iloc[0]
            alerts.append(
                {
                    "code": "unusual_volume",
                    "severity": "low",
                    "strike": int(float(row["strike_price"])),
                    "expiry": expiry,
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
