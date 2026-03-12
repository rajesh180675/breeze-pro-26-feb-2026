"""Persistence-oriented adapters for option-chain workflows."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd


def load_replay_frame(db: Any, instrument: str, expiry: str, replay_ts: str) -> pd.DataFrame:
    rows = db.get_option_chain_snapshot_at_or_before(instrument, expiry, replay_ts)
    return pd.DataFrame(rows)


def load_intraday_snapshot_frame(
    db: Any,
    instrument: str,
    expiry: str,
    trade_date: str,
    limit: int = 5000,
    as_of_ts: str = "",
) -> pd.DataFrame:
    rows = db.get_option_chain_intraday_snapshots(
        instrument,
        expiry=expiry,
        trade_date=trade_date,
        limit=limit,
    )
    frame = pd.DataFrame(rows)
    if frame.empty or not as_of_ts or "snapshot_ts" not in frame.columns:
        return frame
    return frame[frame["snapshot_ts"].astype(str) <= str(as_of_ts)].copy()


def build_window_change_dataset(
    db: Any,
    instrument: str,
    expiry: str,
    as_of_ts: str,
    change_window: str,
) -> pd.DataFrame:
    if not as_of_ts:
        return pd.DataFrame()
    since_open = str(change_window).lower() == "since open"
    window_minutes = 0 if since_open else int(str(change_window).replace("m", "").strip())
    rows = db.get_option_chain_window_comparison(
        instrument,
        expiry,
        as_of_ts=as_of_ts,
        window_minutes=window_minutes,
        since_open=since_open,
    )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["ltp_change"] = pd.to_numeric(out["current_ltp"], errors="coerce").fillna(0) - pd.to_numeric(out["baseline_ltp"], errors="coerce").fillna(0)
    out["current_spread"] = pd.to_numeric(out.get("current_ask", 0), errors="coerce").fillna(0) - pd.to_numeric(out.get("current_bid", 0), errors="coerce").fillna(0)
    out["baseline_spread"] = pd.to_numeric(out.get("baseline_ask", 0), errors="coerce").fillna(0) - pd.to_numeric(out.get("baseline_bid", 0), errors="coerce").fillna(0)
    out["spread_change"] = out["current_spread"] - out["baseline_spread"]
    out["volume_change"] = pd.to_numeric(out["current_volume"], errors="coerce").fillna(0) - pd.to_numeric(out["baseline_volume"], errors="coerce").fillna(0)
    out["open_interest_change"] = pd.to_numeric(out["current_open_interest"], errors="coerce").fillna(0) - pd.to_numeric(out["baseline_open_interest"], errors="coerce").fillna(0)
    out["iv_change"] = pd.to_numeric(out["current_iv"], errors="coerce").fillna(0) - pd.to_numeric(out["baseline_iv"], errors="coerce").fillna(0)
    return out


def build_session_iv_extremes(db: Any, instrument: str, expiry: str, trade_date: str) -> pd.DataFrame:
    rows = db.get_option_chain_intraday_snapshots(instrument, expiry=expiry, trade_date=trade_date, limit=20000)
    if not rows:
        return pd.DataFrame(columns=["strike", "option_type", "session_iv_low", "session_iv_high"])
    frame = pd.DataFrame(rows)
    grouped = (
        frame.groupby(["strike", "option_type"], dropna=True)["iv"]
        .agg(session_iv_low="min", session_iv_high="max")
        .reset_index()
        .sort_values(["strike", "option_type"])
    )
    return grouped


def build_top_movers(change_df: pd.DataFrame, top_n: int = 5) -> Dict[str, pd.DataFrame]:
    if change_df.empty:
        return {}
    ordered = change_df.copy()
    return {
        "oi_addition": ordered.sort_values("open_interest_change", ascending=False).head(top_n),
        "oi_reduction": ordered.sort_values("open_interest_change", ascending=True).head(top_n),
        "volume_burst": ordered.sort_values("volume_change", ascending=False).head(top_n),
        "iv_shift": ordered.sort_values("iv_change", ascending=False).head(top_n),
        "spread_widening": ordered.sort_values("spread_change", ascending=False).head(top_n),
    }
