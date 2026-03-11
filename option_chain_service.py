"""Service helpers for assembling the option-chain workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

import app_config as C
from helpers import add_greeks_to_chain, estimate_atm_strike, process_option_chain, safe_float
from option_chain_metrics import (
    build_expiry_summary,
    calculate_expected_move,
    calculate_iv_percentile,
    calculate_iv_zscore,
    calculate_liquidity_score,
    calculate_max_pain,
    calculate_pcr,
    classify_oi_buildup,
    detect_gamma_walls,
    normalize_iv,
)


def _make_option_key(exchange: str, stock_code: str, expiry: str, strike: float, right_key: str) -> str:
    parts = [exchange, stock_code, "options", str(expiry)[:10], str(float(strike)), right_key]
    return "|".join(parts)


def fetch_option_chain_snapshot(client: Any, stock_code: str, exchange: str, expiry: str) -> pd.DataFrame:
    response = client.get_option_chain(stock_code, exchange, expiry)
    if not response.get("success"):
        raise ValueError(response.get("message") or "Option-chain fetch failed")
    return process_option_chain(response.get("data", {}))


def filter_option_chain(df: pd.DataFrame, atm: float, strikes_per_side: int, show_all: bool = False) -> pd.DataFrame:
    if df.empty or show_all or "strike_price" not in df.columns or atm <= 0:
        return df.copy()
    strikes = sorted(pd.to_numeric(df["strike_price"], errors="coerce").dropna().unique())
    if not strikes:
        return df.copy()
    idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm))
    visible = strikes[max(0, idx - strikes_per_side): min(len(strikes), idx + strikes_per_side + 1)]
    return df[df["strike_price"].isin(visible)].copy()


def merge_live_overlay(
    df: pd.DataFrame,
    instrument: str,
    expiry: str,
    token_map: Dict[str, str],
) -> pd.DataFrame:
    if df.empty or not token_map:
        return df.copy()
    import live_feed as lf

    cfg = C.get_instrument(instrument)
    tick_store = lf.get_tick_store()
    out = df.copy()
    ltps: List[float] = []
    bids: List[float] = []
    asks: List[float] = []
    bid_qtys: List[float] = []
    ask_qtys: List[float] = []
    volumes: List[float] = []
    open_interests: List[float] = []
    oi_changes: List[float] = []
    quote_ages: List[float] = []
    now_ts = datetime.now(timezone.utc).timestamp()
    for _, row in out.iterrows():
        strike = safe_float(row.get("strike_price", 0))
        right = str(row.get("right", "")).lower()
        right_key = "call" if "call" in right or "ce" in right else "put"
        token = token_map.get(_make_option_key(cfg.exchange, cfg.api_code, expiry, strike, right_key))
        tick = tick_store.get_latest(token) if token else None
        ltps.append(tick.ltp if tick and tick.ltp > 0 else safe_float(row.get("ltp", 0)))
        bids.append(tick.best_bid if tick and tick.best_bid > 0 else safe_float(row.get("best_bid_price", row.get("bid", 0))))
        asks.append(tick.best_ask if tick and tick.best_ask > 0 else safe_float(row.get("best_offer_price", row.get("ask", 0))))
        bid_qtys.append(tick.best_bid_qty if tick else safe_float(row.get("bid_qty", 0)))
        ask_qtys.append(tick.best_ask_qty if tick else safe_float(row.get("offer_qty", row.get("ask_qty", 0))))
        volumes.append(tick.volume if tick else safe_float(row.get("volume", 0)))
        open_interests.append(tick.open_interest if tick else safe_float(row.get("open_interest", 0)))
        oi_changes.append(tick.oi_change if tick else safe_float(row.get("oi_change", 0)))
        quote_ages.append((now_ts - tick.received_at) if tick else np.nan)
    out["ltp"] = ltps
    out["best_bid_price"] = bids
    out["best_offer_price"] = asks
    out["bid_qty"] = bid_qtys
    out["offer_qty"] = ask_qtys
    out["volume"] = volumes
    out["open_interest"] = open_interests
    out["oi_change"] = oi_changes
    out["quote_age_seconds"] = quote_ages
    return out


def enrich_option_chain(
    df: pd.DataFrame,
    instrument: str,
    expiry: str,
    spot: float,
    history_provider: Optional[Any] = None,
    volume_baseline_map: Optional[Dict[Any, float]] = None,
    include_greeks: bool = True,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    if include_greeks and spot > 0:
        out = add_greeks_to_chain(out, spot, expiry)
    out["iv_numeric"] = pd.to_numeric(out.get("iv", 0), errors="coerce").fillna(0).map(normalize_iv)
    out["bid"] = pd.to_numeric(out.get("best_bid_price", 0), errors="coerce").fillna(0)
    out["ask"] = pd.to_numeric(out.get("best_offer_price", 0), errors="coerce").fillna(0)
    out["spread"] = (out["ask"] - out["bid"]).clip(lower=0)
    mid = ((out["ask"] + out["bid"]) / 2.0).replace(0, np.nan)
    out["mid_price"] = mid.fillna(pd.to_numeric(out.get("ltp", 0), errors="coerce").fillna(0))
    out["spread_pct"] = np.where(out["mid_price"] > 0, (out["spread"] / out["mid_price"]) * 100.0, 0.0)
    qty_total = pd.to_numeric(out.get("bid_qty", 0), errors="coerce").fillna(0) + pd.to_numeric(out.get("offer_qty", 0), errors="coerce").fillna(0)
    out["bid_ask_imbalance"] = np.where(qty_total > 0, (pd.to_numeric(out.get("bid_qty", 0), errors="coerce").fillna(0) - pd.to_numeric(out.get("offer_qty", 0), errors="coerce").fillna(0)) / qty_total, 0.0)
    out["distance_from_spot"] = pd.to_numeric(out.get("strike_price", 0), errors="coerce").fillna(0) - float(spot or 0)
    out["notional_oi"] = pd.to_numeric(out.get("open_interest", 0), errors="coerce").fillna(0) * out["mid_price"]
    out["ltp_change"] = pd.to_numeric(out.get("ltp", 0), errors="coerce").fillna(0) - pd.to_numeric(out.get("close", 0), errors="coerce").fillna(0)
    out["oi_buildup"] = [
        classify_oi_buildup(float(ltp_change), float(oi_change))
        for ltp_change, oi_change in zip(out["ltp_change"], pd.to_numeric(out.get("oi_change", 0), errors="coerce").fillna(0))
    ]
    iv_percentiles: List[float] = []
    iv_zscores: List[float] = []
    avg_volumes: List[float] = []
    liquidity_scores: List[float] = []
    for _, row in out.iterrows():
        strike = int(safe_float(row.get("strike_price", 0), 0))
        right = str(row.get("right", "")).lower()
        option_type = "CE" if ("call" in right or "ce" in right) else "PE"
        history = history_provider(instrument, strike, option_type, 30) if history_provider else []
        iv_percentiles.append(calculate_iv_percentile(float(row.get("iv_numeric", 0)), history))
        iv_zscores.append(calculate_iv_zscore(float(row.get("iv_numeric", 0)), history))
        avg_volume = float((volume_baseline_map or {}).get((strike, option_type), 0.0))
        avg_volumes.append(avg_volume)
        liquidity_scores.append(calculate_liquidity_score(row.to_dict(), row.get("quote_age_seconds")))
    out["iv_percentile"] = iv_percentiles
    out["iv_zscore"] = iv_zscores
    out["avg_volume"] = avg_volumes
    out["volume_spike"] = np.where(pd.to_numeric(out.get("volume", 0), errors="coerce").fillna(0) > (pd.Series(avg_volumes).replace(0, np.nan) * 3), True, False)
    out["liquidity_score"] = liquidity_scores
    return out


def build_option_chain_ladder(
    df: pd.DataFrame,
    spot: float,
    pinned_strikes: Optional[Iterable[int]] = None,
) -> pd.DataFrame:
    if df.empty or "strike_price" not in df.columns:
        return pd.DataFrame()
    pinned = {int(s) for s in (pinned_strikes or [])}
    strikes = sorted(pd.to_numeric(df["strike_price"], errors="coerce").dropna().unique())
    atm = estimate_atm_strike(df, spot=spot)
    max_pain = calculate_max_pain(df)
    rows: List[Dict[str, Any]] = []
    for strike in strikes:
        row: Dict[str, Any] = {
            "call_ltp": 0.0,
            "call_oi": 0.0,
            "call_oi_change": 0.0,
            "call_volume": 0.0,
            "call_iv": 0.0,
            "call_liquidity": 0.0,
            "strike": int(float(strike)),
            "put_ltp": 0.0,
            "put_oi": 0.0,
            "put_oi_change": 0.0,
            "put_volume": 0.0,
            "put_iv": 0.0,
            "put_liquidity": 0.0,
            "distance_from_spot": round(float(strike) - spot, 2) if spot > 0 else 0.0,
            "is_atm": int(float(strike) == float(atm)),
            "is_max_pain": int(float(strike) == float(max_pain)),
            "is_pinned": int(int(float(strike)) in pinned),
        }
        strike_rows = df[df["strike_price"] == strike]
        for _, option_row in strike_rows.iterrows():
            prefix = "call" if option_row.get("right") == "Call" else "put"
            row[f"{prefix}_ltp"] = float(option_row.get("ltp", 0) or 0)
            row[f"{prefix}_oi"] = float(option_row.get("open_interest", 0) or 0)
            row[f"{prefix}_oi_change"] = float(option_row.get("oi_change", 0) or 0)
            row[f"{prefix}_volume"] = float(option_row.get("volume", 0) or 0)
            row[f"{prefix}_iv"] = float(option_row.get("iv_numeric", normalize_iv(option_row.get("iv", 0))) or 0)
            row[f"{prefix}_liquidity"] = float(option_row.get("liquidity_score", 0) or 0)
        rows.append(row)
    ladder = pd.DataFrame(rows)
    return ladder.sort_values(["is_pinned", "is_atm", "strike"], ascending=[False, False, True]).reset_index(drop=True)


def build_expiry_strip(
    expiry_frames: Dict[str, pd.DataFrame],
    spot: float,
    dte_provider: Any,
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for expiry, frame in expiry_frames.items():
        days_to_expiry = int(dte_provider(expiry))
        summary = build_expiry_summary(frame, spot=spot, days_to_expiry=days_to_expiry)
        summary["expiry"] = expiry
        summary["dte"] = days_to_expiry
        summaries.append(summary)
    return summaries


def build_gamma_profile(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not {"strike_price", "gamma", "open_interest"}.issubset(df.columns):
        return pd.DataFrame(columns=["strike_price", "net_gamma"])
    working = df.copy()
    working["gamma"] = pd.to_numeric(working["gamma"], errors="coerce").fillna(0.0)
    working["open_interest"] = pd.to_numeric(working["open_interest"], errors="coerce").fillna(0.0)
    working["net_gamma"] = np.where(
        working["right"].eq("Put"),
        -working["gamma"] * working["open_interest"],
        working["gamma"] * working["open_interest"],
    )
    return working.groupby("strike_price", dropna=True)["net_gamma"].sum().reset_index().sort_values("strike_price")


def load_replay_frame(db: Any, instrument: str, expiry: str, replay_ts: str) -> pd.DataFrame:
    rows = db.get_option_chain_snapshot_at_or_before(instrument, expiry, replay_ts)
    return pd.DataFrame(rows)


def summarize_chain(df: pd.DataFrame, spot: float, days_to_expiry: int) -> Dict[str, Any]:
    atm = estimate_atm_strike(df, spot=spot)
    expected_move = calculate_expected_move(df, spot=spot, atm_strike=atm, days_to_expiry=days_to_expiry)
    return {
        "atm": atm,
        "pcr": calculate_pcr(df),
        "max_pain": calculate_max_pain(df),
        "expected_move": expected_move,
        "gamma_walls": detect_gamma_walls(df),
    }
