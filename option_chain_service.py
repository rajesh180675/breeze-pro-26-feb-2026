"""Service helpers for assembling the option-chain workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

import app_config as C
from helpers import add_greeks_to_chain, safe_float
from option_chain_alerts import build_commentary, evaluate_alerts
from option_chain_metrics import (
    build_expiry_summary,
    calculate_expected_move,
    calculate_charm,
    calculate_iv_percentile,
    calculate_iv_zscore,
    calculate_liquidity_score,
    calculate_max_pain,
    calculate_pcr,
    calculate_vanna,
    classify_oi_buildup,
    detect_gamma_walls,
    normalize_iv,
)
from option_chain_utils import estimate_atm_strike, process_option_chain


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

    def _numeric_column(name: str, default: float = 0.0) -> pd.Series:
        if name in out.columns:
            return pd.to_numeric(out[name], errors="coerce").fillna(default)
        return pd.Series(default, index=out.index, dtype=float)

    if include_greeks and spot > 0:
        out = add_greeks_to_chain(out, spot, expiry)
    out["iv_numeric"] = _numeric_column("iv").map(normalize_iv)
    out["bid"] = _numeric_column("best_bid_price")
    out["ask"] = _numeric_column("best_offer_price")
    out["spread"] = (out["ask"] - out["bid"]).clip(lower=0)
    mid = ((out["ask"] + out["bid"]) / 2.0).replace(0, np.nan)
    out["mid_price"] = mid.fillna(_numeric_column("ltp"))
    out["spread_pct"] = np.where(out["mid_price"] > 0, (out["spread"] / out["mid_price"]) * 100.0, 0.0)
    bid_qty = _numeric_column("bid_qty")
    offer_qty = _numeric_column("offer_qty")
    qty_total = bid_qty + offer_qty
    out["bid_ask_imbalance"] = np.where(qty_total > 0, (bid_qty - offer_qty) / qty_total, 0.0)
    out["distance_from_spot"] = _numeric_column("strike_price") - float(spot or 0)
    out["notional_oi"] = _numeric_column("open_interest") * out["mid_price"]
    out["ltp_change"] = _numeric_column("ltp") - _numeric_column("close")
    out["oi_buildup"] = [
        classify_oi_buildup(float(ltp_change), float(oi_change))
        for ltp_change, oi_change in zip(out["ltp_change"], _numeric_column("oi_change"))
    ]
    iv_percentiles: List[float] = []
    iv_zscores: List[float] = []
    avg_volumes: List[float] = []
    liquidity_scores: List[float] = []
    vannas: List[float] = []
    charms: List[float] = []
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
        vannas.append(calculate_vanna(spot=spot, strike=strike, expiry=expiry, option_type=option_type, iv=float(row.get("iv_numeric", 0))))
        charms.append(calculate_charm(spot=spot, strike=strike, expiry=expiry, option_type=option_type, iv=float(row.get("iv_numeric", 0))))
    out["iv_percentile"] = iv_percentiles
    out["iv_zscore"] = iv_zscores
    out["avg_volume"] = avg_volumes
    out["volume_spike"] = np.where(_numeric_column("volume") > (pd.Series(avg_volumes).replace(0, np.nan) * 3), True, False)
    out["liquidity_score"] = liquidity_scores
    out["vanna"] = vannas
    out["charm"] = charms
    out["net_vanna"] = _numeric_column("vanna") * _numeric_column("open_interest")
    out["net_charm"] = _numeric_column("charm") * _numeric_column("open_interest")
    return out


def build_option_chain_ladder(
    df: pd.DataFrame,
    spot: float,
    pinned_strikes: Optional[Iterable[int]] = None,
    selected_strike: Optional[int] = None,
    sticky_atm: bool = True,
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
            "is_selected": int(selected_strike is not None and int(float(strike)) == int(selected_strike)),
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
    sort_columns = ["is_selected", "is_pinned", "is_atm", "strike"] if sticky_atm else ["is_selected", "is_pinned", "strike"]
    ascending = [False, False, False, True] if sticky_atm else [False, False, True]
    return ladder.sort_values(sort_columns, ascending=ascending).reset_index(drop=True)


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
    return sorted(summaries, key=lambda row: row["expiry"])


def build_multi_expiry_dataset(
    expiry_frames: Dict[str, pd.DataFrame],
    metric: str,
    normalization_mode: str = "absolute",
    spot: float = 0.0,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for expiry, frame in expiry_frames.items():
        if frame.empty or metric not in frame.columns:
            continue
        grouped = frame.groupby(["strike_price", "right"], dropna=True)[metric].sum().reset_index()
        grouped["expiry"] = expiry
        atm = estimate_atm_strike(frame, spot=spot)
        if str(normalization_mode).lower() == "atm offset":
            grouped["comparison_axis"] = pd.to_numeric(grouped["strike_price"], errors="coerce").fillna(0.0) - float(atm or 0.0)
        elif str(normalization_mode).lower() == "atm %":
            grouped["comparison_axis"] = np.where(float(atm or 0.0) > 0, ((pd.to_numeric(grouped["strike_price"], errors="coerce").fillna(0.0) / float(atm)) - 1.0) * 100.0, 0.0)
        else:
            grouped["comparison_axis"] = pd.to_numeric(grouped["strike_price"], errors="coerce").fillna(0.0)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["strike_price", "right", metric, "expiry", "comparison_axis"])


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


def build_vanna_profile(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not {"strike_price", "net_vanna"}.issubset(df.columns):
        return pd.DataFrame(columns=["strike_price", "net_vanna"])
    return (
        df.groupby("strike_price", dropna=True)["net_vanna"]
        .sum()
        .reset_index()
        .sort_values("strike_price")
    )


def build_charm_profile(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not {"strike_price", "net_charm"}.issubset(df.columns):
        return pd.DataFrame(columns=["strike_price", "net_charm"])
    return (
        df.groupby("strike_price", dropna=True)["net_charm"]
        .sum()
        .reset_index()
        .sort_values("strike_price")
    )


def summarize_alert_commentary_payload(
    alerts: List[Dict[str, Any]],
    commentary: List[str],
    top_n_alerts: int = 5,
    top_n_commentary: int = 4,
) -> Dict[str, List[Any]]:
    return {
        "alerts": alerts[:top_n_alerts],
        "commentary": commentary[:top_n_commentary],
    }


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


def compose_option_chain_workspace(
    db: Any,
    instrument: str,
    expiry: str,
    days_to_expiry: int,
    base_df: pd.DataFrame,
    display_df: pd.DataFrame,
    compare_frames: Dict[str, pd.DataFrame],
    replay_timestamps: List[str],
    replay_ts: str,
    change_window: str,
    spot: float,
    baseline_map: Optional[Dict[Any, float]] = None,
    history_provider: Optional[Any] = None,
    monitored_strikes: Optional[Iterable[int]] = None,
    selected_strike: Optional[int] = None,
    sticky_atm: bool = True,
    show_only_liquid: bool = False,
    show_only_unusual: bool = False,
    include_greeks: bool = True,
    include_oi_change_pct: bool = False,
    include_iv_percentile: bool = False,
    include_max_pain_marker: bool = False,
    dte_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    summary = summarize_chain(base_df, spot, days_to_expiry)
    atm = summary["atm"]
    max_pain = summary["max_pain"]
    expiry_strip = build_expiry_strip(compare_frames, spot, dte_provider or (lambda exp: 0))

    ddf = enrich_option_chain(
        display_df,
        instrument=instrument,
        expiry=expiry,
        spot=spot,
        history_provider=history_provider,
        volume_baseline_map=baseline_map,
        include_greeks=include_greeks,
    )
    if include_oi_change_pct and {"open_interest", "oi_change"}.issubset(ddf.columns):
        oi_base = ddf["open_interest"].replace(0, np.nan)
        ddf["OI Change %"] = ((ddf["oi_change"] / oi_base) * 100.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if show_only_liquid and "liquidity_score" in ddf.columns:
        ddf = ddf[ddf["liquidity_score"] >= 50].copy()
    if show_only_unusual and "volume_spike" in ddf.columns:
        ddf = ddf[ddf["volume_spike"]].copy()
    if include_iv_percentile and "iv_percentile" in ddf.columns:
        ddf["IV Percentile"] = ddf["iv_percentile"]
    if include_max_pain_marker and "strike_price" in ddf.columns:
        ddf["Strike"] = ddf["strike_price"].apply(
            lambda strike: f"MP {int(strike)}" if safe_float(strike) == safe_float(max_pain) else str(int(strike))
        )

    previous_df = pd.DataFrame()
    if replay_timestamps:
        reference_ts = replay_ts or replay_timestamps[-1]
        previous_ts = next((ts for ts in reversed(replay_timestamps) if ts < reference_ts), None)
        if previous_ts:
            previous_df = load_replay_frame(db, instrument, expiry, previous_ts)
            if not previous_df.empty:
                previous_df = enrich_option_chain(
                    previous_df,
                    instrument=instrument,
                    expiry=expiry,
                    spot=spot,
                    history_provider=history_provider,
                    volume_baseline_map=baseline_map,
                    include_greeks=False,
                )

    call_wall = None
    put_wall = None
    if not ddf.empty and "right" in ddf.columns and "open_interest" in ddf.columns:
        call_side = ddf[ddf["right"] == "Call"]
        put_side = ddf[ddf["right"] == "Put"]
        if not call_side.empty:
            call_wall = int(float(call_side.loc[call_side["open_interest"].astype(float).idxmax(), "strike_price"]))
        if not put_side.empty:
            put_wall = int(float(put_side.loc[put_side["open_interest"].astype(float).idxmax(), "strike_price"]))

    pinned_strikes = [int(strike) for strike in monitored_strikes or [] if int(strike) > 0]
    if atm:
        pinned_strikes.insert(0, int(atm))
    if max_pain:
        pinned_strikes.insert(1 if pinned_strikes else 0, int(max_pain))
    if call_wall:
        pinned_strikes.append(call_wall)
    if put_wall:
        pinned_strikes.append(put_wall)
    pinned_strikes = list(dict.fromkeys(pinned_strikes))

    ladder = build_option_chain_ladder(
        ddf,
        spot,
        pinned_strikes=pinned_strikes,
        selected_strike=selected_strike,
        sticky_atm=sticky_atm,
    )
    as_of_ts = replay_ts or (replay_timestamps[-1] if replay_timestamps else "")
    alerts = evaluate_alerts(
        ddf,
        previous_df=previous_df,
        spot=spot,
        expiry=expiry,
        monitored_strikes=list(monitored_strikes or []),
        snapshot_ts=as_of_ts,
    )
    commentary = build_commentary(ddf, alerts, spot=spot, expiry=expiry)
    change_df = build_window_change_dataset(
        db,
        instrument,
        expiry,
        as_of_ts=as_of_ts,
        change_window=change_window,
    ) if as_of_ts else pd.DataFrame()
    trade_date = as_of_ts[:10] if as_of_ts else datetime.now(timezone.utc).date().isoformat()
    replay_chart_df = load_intraday_snapshot_frame(
        db,
        instrument,
        expiry,
        trade_date=trade_date,
        limit=5000,
        as_of_ts=as_of_ts,
    )
    session_iv_extremes = build_session_iv_extremes(db, instrument, expiry, trade_date=trade_date)
    return {
        "summary": summary,
        "atm": atm,
        "max_pain": max_pain,
        "pinned_strikes": pinned_strikes,
        "display_df": ddf,
        "previous_df": previous_df,
        "ladder": ladder,
        "alerts": alerts,
        "commentary_payload": summarize_alert_commentary_payload(alerts, commentary),
        "gamma_profile": build_gamma_profile(ddf),
        "vanna_profile": build_vanna_profile(ddf),
        "charm_profile": build_charm_profile(ddf),
        "change_df": change_df,
        "top_movers": build_top_movers(change_df),
        "session_iv_extremes": session_iv_extremes,
        "as_of_ts": as_of_ts,
        "replay_chart_df": replay_chart_df,
        "expiry_strip": expiry_strip,
    }


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
