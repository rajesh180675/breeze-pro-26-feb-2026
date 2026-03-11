"""Utility functions for option-chain parsing and presentation."""

from __future__ import annotations

import logging
from typing import Dict

import pandas as pd

log = logging.getLogger(__name__)

NUMERIC_COLS = [
    "strike_price",
    "ltp",
    "best_bid_price",
    "best_offer_price",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "ltp_percent_change",
    "oi_change",
    "iv",
    "bid_qty",
    "offer_qty",
]


def process_option_chain(raw_data: Dict) -> pd.DataFrame:
    if not raw_data:
        log.warning("process_option_chain: received empty/None response")
        return pd.DataFrame()

    breeze_status = raw_data.get("Status")
    breeze_error = raw_data.get("Error")
    if breeze_error:
        log.error("process_option_chain: Breeze API error: status=%s, error=%s", breeze_status, breeze_error)
        return pd.DataFrame()
    if isinstance(breeze_status, int) and breeze_status >= 400:
        log.error("process_option_chain: Breeze API non-200 status: %s", breeze_status)
        return pd.DataFrame()

    if "Success" not in raw_data:
        log.warning("process_option_chain: 'Success' key missing. Keys present: %s", list(raw_data.keys()))
        return pd.DataFrame()

    records = raw_data.get("Success")
    if not records:
        log.warning("process_option_chain: Success is empty or None. Full response: %s", raw_data)
        return pd.DataFrame()
    if not isinstance(records, list):
        log.warning("process_option_chain: Success is not a list, got %s", type(records))
        return pd.DataFrame()

    df = pd.DataFrame(records)
    if df.empty:
        log.warning("process_option_chain: DataFrame is empty after construction")
        return df

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "right" in df.columns:
        df["right"] = df["right"].astype(str).str.strip().str.capitalize()
    return df


def create_pivot_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "strike_price" not in df.columns or "right" not in df.columns:
        return pd.DataFrame()
    pivot_fields = {
        "open_interest": "OI",
        "oi_change": "DeltaOI",
        "volume": "Vol",
        "ltp": "LTP",
        "best_bid_price": "Bid",
        "best_offer_price": "Ask",
        "iv": "IV%",
    }
    available = {k: v for k, v in pivot_fields.items() if k in df.columns}
    if not available:
        return df
    calls = df[df["right"] == "Call"].set_index("strike_price")
    puts = df[df["right"] == "Put"].set_index("strike_price")
    all_strikes = sorted(df["strike_price"].dropna().unique())
    result = pd.DataFrame({"Strike": all_strikes}).set_index("Strike")
    for field, label in available.items():
        if field in calls.columns:
            result[f"C_{label}"] = calls[field]
        if field in puts.columns:
            result[f"P_{label}"] = puts[field]
    result = result.fillna(0).reset_index()
    call_cols = [c for c in result.columns if c.startswith("C_")]
    put_cols = [c for c in result.columns if c.startswith("P_")]
    return result[call_cols + ["Strike"] + put_cols]


def estimate_atm_strike(df: pd.DataFrame, spot: float = 0.0) -> float:
    if df.empty or "strike_price" not in df.columns:
        return 0.0

    strikes = sorted(pd.to_numeric(df["strike_price"], errors="coerce").dropna().unique())
    if not strikes:
        return 0.0
    if spot > 0:
        return float(min(strikes, key=lambda s: abs(s - spot)))

    if "right" in df.columns and "ltp" in df.columns:
        calls = df[(df["right"] == "Call") & (pd.to_numeric(df["ltp"], errors="coerce") > 0)][["strike_price", "ltp"]].set_index("strike_price")
        puts = df[(df["right"] == "Put") & (pd.to_numeric(df["ltp"], errors="coerce") > 0)][["strike_price", "ltp"]].set_index("strike_price")
        combined = calls.join(puts, lsuffix="_call", rsuffix="_put").dropna()
        if not combined.empty:
            combined["diff"] = (combined["ltp_call"] - combined["ltp_put"]).abs()
            return float(combined["diff"].idxmin())

    if "open_interest" in df.columns and "right" in df.columns:
        try:
            call_oi = df[df["right"] == "Call"].groupby("strike_price")["open_interest"].sum()
            put_oi = df[df["right"] == "Put"].groupby("strike_price")["open_interest"].sum()
            total = call_oi.add(put_oi, fill_value=0).dropna()
            total = total[total > 0]
            if not total.empty:
                threshold = total.quantile(0.80)
                top_strikes = sorted(total[total >= threshold].index.tolist())
                return float(top_strikes[len(top_strikes) // 2])
        except Exception:
            pass

    return float(strikes[len(strikes) // 2])
