"""Market-data adapters for option-chain workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import numpy as np
import pandas as pd

import app_config as C
from helpers import safe_float

from app.domain.option_chain.utils import process_option_chain


def _make_option_key(exchange: str, stock_code: str, expiry: str, strike: float, right_key: str) -> str:
    parts = [exchange, stock_code, "options", str(expiry)[:10], str(float(strike)), right_key]
    return "|".join(parts)


def fetch_option_chain_snapshot(client: Any, stock_code: str, exchange: str, expiry: str) -> pd.DataFrame:
    response = client.get_option_chain(stock_code, exchange, expiry)
    if not response.get("success"):
        raise ValueError(response.get("message") or "Option-chain fetch failed")
    return process_option_chain(response.get("data", {}))


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

