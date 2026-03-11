"""Controller helpers for option-chain page controls and data loading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

import app_config as C
from helpers import APIResponse, safe_float
from option_chain_service import fetch_option_chain_snapshot, load_replay_frame, merge_live_overlay
from option_chain_workspace import resolve_monitored_strike_defaults


@dataclass
class OptionChainControls:
    inst: str
    cfg: Any
    expiry: str
    compare_expiries: List[str]
    show_all: bool
    n_strikes: int
    refresh: bool
    show_greeks: bool
    view: str
    quote_mode: str
    chain_opt_oi_heatmap: bool
    chain_opt_volume_spike: bool
    chain_opt_pcr_gauge: bool
    chain_opt_max_pain_marker: bool
    chain_opt_iv_percentile: bool
    chain_opt_export: bool
    sticky_atm: bool
    show_only_liquid: bool
    show_only_unusual: bool
    change_window: str
    normalization_mode: str
    chart_tab: str


def render_option_chain_controls(
    state: Dict[str, Any],
    format_expiry: Callable[[str], str],
    format_expiry_short: Callable[[str], str],
) -> Optional[OptionChainControls]:
    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 1])
    with c1:
        inst = st.selectbox("Instrument", list(C.INSTRUMENTS.keys()), key="oc_inst")
    cfg = C.get_instrument(inst)
    with c2:
        expiries = C.get_next_expiries(inst, 6)
        if not expiries:
            st.error("No expiries available")
            return None
        expiry = st.selectbox("Expiry", expiries, format_func=format_expiry, key="oc_exp")
    with c3:
        compare_default = [exp for exp in state.get("compare_expiries", []) if exp in expiries and exp != expiry]
        compare_expiries = st.multiselect(
            "Compare Expiries",
            options=[exp for exp in expiries if exp != expiry],
            default=compare_default[:2],
            format_func=format_expiry,
            key="oc_compare_expiries",
        )[:2]
    natural_expiry = C.get_natural_expiry_for(inst, expiry)
    if natural_expiry and natural_expiry != expiry:
        st.info(
            f"📅 **Holiday-adjusted expiry** — {inst} natural expiry "
            f"({format_expiry_short(natural_expiry)}) falls on a market holiday. "
            f"NSE moved it to **{format_expiry_short(expiry)}**."
        )
    with c4:
        show_all = st.checkbox("Show All Strikes", value=False, key="oc_all")
        n_strikes = st.slider(
            "Strikes ±",
            5,
            100,
            40,
            key="oc_n",
            disabled=show_all,
            help="Number of strikes to show above and below ATM. Ignored when 'Show All Strikes' is checked.",
        )
    with c5:
        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        refresh = col1.button("🔄", key="oc_ref", help="Refresh chain")
        show_greeks = col2.checkbox("Greeks", True, key="oc_g")

    view = st.radio("View", ["Ladder", "Flat", "Calls Only", "Puts Only"], horizontal=True, key="oc_v")
    quote_mode = st.radio("Quote Mode", ["🔴 Live WS", "📦 Snapshot", "⏪ Replay"], horizontal=True, key="oc_quote_mode")
    with st.sidebar.expander("⛓️ Chain Options"):
        chain_opt_oi_heatmap = st.checkbox("OI Change % Heatmap", value=True, key="oc_opt_oi_heatmap")
        chain_opt_volume_spike = st.checkbox("Volume Spike Alert", value=True, key="oc_opt_vol_spike")
        chain_opt_pcr_gauge = st.checkbox("PCR Gauge", value=True, key="oc_opt_pcr_gauge")
        chain_opt_max_pain_marker = st.checkbox("Max Pain Marker", value=True, key="oc_opt_mp_marker")
        chain_opt_iv_percentile = st.checkbox("IV Percentile", value=False, key="oc_opt_iv_percentile")
        chain_opt_export = st.checkbox("Export Button", value=True, key="oc_opt_export")
        sticky_atm = st.checkbox("Sticky ATM Row", value=bool(state.get("sticky_atm", True)), key="oc_sticky_atm")
        show_only_liquid = st.checkbox("Show Only Liquid", value=bool(state.get("show_only_liquid")), key="oc_only_liquid")
        show_only_unusual = st.checkbox("Show Only Unusual Activity", value=bool(state.get("show_only_unusual")), key="oc_only_unusual")
        change_window = st.selectbox(
            "Change Window",
            ["Since Open", "5m", "15m", "30m", "60m"],
            index=["Since Open", "5m", "15m", "30m", "60m"].index(state.get("change_window", "Since Open")),
            key="oc_change_window",
        )
        normalization_mode = st.selectbox(
            "Compare Normalization",
            ["Absolute", "ATM Offset", "ATM %"],
            index=["Absolute", "ATM Offset", "ATM %"].index(
                str(state.get("normalization_mode", "Absolute")).title()
                if str(state.get("normalization_mode", "Absolute")).lower() != "atm %"
                else "ATM %"
            ),
            key="oc_normalization_mode",
        )
        chart_tab = st.selectbox(
            "Chart Tab",
            ["OI Profile", "Delta OI", "IV Smile", "Compare OI", "Compare IV Smile", "Term Structure", "Expected Move", "OI Heatmap", "Skew Replay", "Gamma", "Vanna", "Charm", "Liquidity"],
            key="oc_chart_tab",
        )

    return OptionChainControls(
        inst=inst,
        cfg=cfg,
        expiry=expiry,
        compare_expiries=compare_expiries,
        show_all=show_all,
        n_strikes=n_strikes,
        refresh=refresh,
        show_greeks=show_greeks,
        view=view,
        quote_mode=quote_mode,
        chain_opt_oi_heatmap=chain_opt_oi_heatmap,
        chain_opt_volume_spike=chain_opt_volume_spike,
        chain_opt_pcr_gauge=chain_opt_pcr_gauge,
        chain_opt_max_pain_marker=chain_opt_max_pain_marker,
        chain_opt_iv_percentile=chain_opt_iv_percentile,
        chain_opt_export=chain_opt_export,
        sticky_atm=sticky_atm,
        show_only_liquid=show_only_liquid,
        show_only_unusual=show_only_unusual,
        change_window=change_window,
        normalization_mode=normalization_mode,
        chart_tab=chart_tab,
    )


def invalidate_option_chain_cache(cache_manager: Any, api_code: str, expiry: str, compare_expiries: Sequence[str]) -> None:
    cache_manager.invalidate(f"oc_{api_code}_{expiry}", "option_chain")
    for cmp_expiry in compare_expiries:
        cache_manager.invalidate(f"oc_{api_code}_{cmp_expiry}", "option_chain")


def load_cached_option_chain(
    cache_manager: Any,
    client: Any,
    db: Any,
    instrument: str,
    cfg: Any,
    expiry: str,
    spinner: Callable[[str], Any],
) -> pd.DataFrame:
    cache_key = f"oc_{cfg.api_code}_{expiry}"
    cached = cache_manager.get(cache_key, "option_chain")
    if cached is not None:
        return cached
    with spinner(f"Loading {instrument} option chain..."):
        frame = fetch_option_chain_snapshot(client, cfg.api_code, cfg.exchange, expiry)
    if frame.empty:
        return frame
    try:
        db.record_option_chain_snapshot(instrument, expiry, frame.to_dict("records"))
        db.record_option_chain_intraday_snapshot(instrument, expiry, frame.to_dict("records"))
    except Exception:
        pass
    cache_manager.set(cache_key, frame, "option_chain", C.OC_CACHE_TTL_SECONDS)
    return frame


def load_compare_option_frames(
    loader: Callable[[str], pd.DataFrame],
    expiry: str,
    compare_expiries: Sequence[str],
) -> Dict[str, pd.DataFrame]:
    compare_frames: Dict[str, pd.DataFrame] = {expiry: loader(expiry)}
    for cmp_expiry in compare_expiries:
        try:
            compare_frames[cmp_expiry] = loader(cmp_expiry)
        except Exception:
            continue
    return compare_frames


def load_option_chain_spot(cache_manager: Any, client: Any, cfg: Any, session_state: Dict[str, Any]) -> float:
    spot_key = f"spot_{cfg.api_code}"
    spot = cache_manager.get(spot_key, "spot") or 0.0
    if spot <= 0:
        try:
            spot_resp = client.get_spot_price(cfg.api_code, cfg.exchange)
            if spot_resp.get("success"):
                spot_items = APIResponse(spot_resp).items
                if spot_items:
                    spot = safe_float(spot_items[0].get("ltp", 0))
                    if spot > 0:
                        cache_manager.set(spot_key, spot, "spot", C.SPOT_CACHE_TTL_SECONDS)
        except Exception:
            spot = 0.0
    if spot > 0:
        session_state["last_spot"] = spot
    return spot


def resolve_replay_chain_selection(
    db: Any,
    session_state: Dict[str, Any],
    instrument: str,
    expiry: str,
    quote_mode: str,
    update_state: Callable[..., Dict[str, Any]],
    caption: Callable[[str], None],
    info: Callable[[str], None],
) -> Tuple[List[str], str, pd.DataFrame]:
    replay_timestamps = db.get_option_chain_replay_timestamps(instrument, expiry, limit=120)
    replay_ts = ""
    replay_df = pd.DataFrame()
    if quote_mode != "⏪ Replay":
        return replay_timestamps, replay_ts, replay_df
    if not replay_timestamps:
        info("No stored intraday snapshots yet for replay. Switch to snapshot/live and refresh first.")
        return replay_timestamps, replay_ts, replay_df
    replay_index = st.slider("Replay Snapshot", 0, len(replay_timestamps) - 1, len(replay_timestamps) - 1, key="oc_replay_index")
    replay_ts = replay_timestamps[replay_index]
    update_state(session_state, replay_timestamp=replay_ts)
    replay_df = load_replay_frame(db, instrument, expiry, replay_ts)
    if not replay_df.empty:
        caption(f"Replay snapshot: {replay_ts}")
    return replay_timestamps, replay_ts, replay_df


def sync_option_chain_watchlist(
    db: Any,
    session_state: Dict[str, Any],
    state: Dict[str, Any],
    instrument: str,
    expiry: str,
    all_strikes: Sequence[int],
) -> List[int]:
    persisted_monitored = db.get_option_chain_watchlist(instrument, expiry)
    default_monitored = resolve_monitored_strike_defaults(state.get("monitored_strikes", []), persisted_monitored, all_strikes)
    monitor_strikes = st.sidebar.multiselect(
        "Monitor Strikes",
        options=list(all_strikes),
        default=default_monitored,
        key="oc_monitored_strikes",
    )
    normalized = sorted({int(strike) for strike in monitor_strikes})
    if normalized != persisted_monitored:
        db.sync_option_chain_watchlist(instrument, expiry, normalized)
    session_state["option_chain_workspace_state"] = {
        **session_state.get("option_chain_workspace_state", {}),
        "monitored_strikes": normalized,
    }
    return normalized


def sync_option_chain_live_feed(
    live_feed_module: Any,
    subscribe_fn: Callable[[str, str, List[int], Any], Dict[str, str]],
    session_state: Dict[str, Any],
    instrument: str,
    expiry: str,
    api_code: str,
    visible_strikes: Iterable[int],
    client: Any,
) -> Dict[str, str]:
    visible = sorted({int(strike) for strike in visible_strikes})
    if not visible:
        return {}
    token_map = subscribe_fn(instrument, expiry, visible, client)
    if not token_map:
        return {}
    mgr = live_feed_module.get_live_feed_manager()
    tick_store = live_feed_module.get_tick_store()
    ws_key = f"oc_ws_tokens_{api_code}_{expiry}"
    prev_tokens = set(session_state.get(ws_key, []))
    cur_tokens = {tok for tok in token_map.values() if tok}
    to_remove = sorted(prev_tokens - cur_tokens)
    if mgr and to_remove:
        for tok in to_remove:
            mgr.unsubscribe_quote(tok)
        tick_store.clear_tokens(to_remove)
    if to_remove:
        live_feed_module.unregister_option_chain_tracking(to_remove)
    if cur_tokens:
        live_feed_module.register_option_chain_tracking(instrument, token_map)
    session_state[ws_key] = sorted(cur_tokens)
    return token_map


def apply_option_chain_live_overlay(
    quote_mode: str,
    display_df: pd.DataFrame,
    token_map: Dict[str, str],
    instrument: str,
    expiry: str,
) -> pd.DataFrame:
    if quote_mode != "🔴 Live WS" or display_df.empty or not token_map:
        return display_df
    return merge_live_overlay(display_df, instrument, expiry, token_map)
