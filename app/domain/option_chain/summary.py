"""Summary/header helpers for the option-chain page."""

from __future__ import annotations

from typing import Any, Callable, Dict, Sequence

import streamlit as st

from .metrics import detect_event_premium


def build_option_chain_summary_payload(
    spot: float,
    atm: float,
    pcr: float,
    max_pain: float,
    dte: int,
    expected_move: float,
    total_call_oi: float,
    total_put_oi: float,
    expiry_strip: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    premium_check = None
    if len(expiry_strip) >= 2:
        premium_check = detect_event_premium(expiry_strip[0]["atm_iv"], expiry_strip[1]["atm_iv"])
    return {
        "cards": [
            {"label": "Spot", "value": f"{spot:,.0f}" if spot > 0 else "—", "delta": None, "delta_color": "normal"},
            {"label": "ATM", "value": f"{atm:,.0f}", "delta": None, "delta_color": "normal"},
            {"label": "PCR", "value": f"{pcr:.2f}", "delta": "Bullish" if pcr > 1 else "Bearish", "delta_color": "normal"},
            {"label": "Max Pain", "value": f"{max_pain:,.0f}", "delta": None, "delta_color": "normal"},
            {"label": "DTE", "value": str(dte), "delta": "⚠️ Expiry Soon!" if dte <= 2 else None, "delta_color": "inverse" if dte <= 2 else "normal"},
            {"label": "Expected Move", "value": f"±{expected_move:,.0f}" if expected_move else "—", "delta": None, "delta_color": "normal"},
            {"label": "Call OI", "value": total_call_oi, "delta": None, "delta_color": "normal"},
            {"label": "Put OI", "value": total_put_oi, "delta": None, "delta_color": "normal"},
        ],
        "expiry_strip": list(expiry_strip[:3]),
        "premium_check": premium_check,
        "show_expiry_warning": dte <= 0,
    }


def render_option_chain_summary(
    payload: Dict[str, Any],
    chain_opt_pcr_gauge: bool,
    format_number: Callable[[float], str],
    format_expiry_short: Callable[[str], str],
    warn_box: Callable[[str], None],
) -> None:
    cards = payload["cards"]
    cols = st.columns(len(cards))
    for idx, card in enumerate(cards):
        value = format_number(card["value"]) if card["label"] in {"Call OI", "Put OI"} else card["value"]
        cols[idx].metric(card["label"], value, card["delta"], delta_color=card["delta_color"])
    pcr_value = next((card["value"] for card in cards if card["label"] == "PCR"), "0.00")
    if chain_opt_pcr_gauge:
        st.progress(max(0.0, min(float(pcr_value) / 2.0, 1.0)), text=f"PCR Gauge: {pcr_value}")
    if payload["show_expiry_warning"]:
        warn_box("⚠️ <b>Expiry Day!</b> Options expire today. Consider squaring off short positions.")
    expiry_strip = payload["expiry_strip"]
    if expiry_strip:
        strip_cols = st.columns(min(len(expiry_strip), 3))
        for idx, expiry_summary in enumerate(expiry_strip):
            strip_cols[idx].metric(
                f"{format_expiry_short(expiry_summary['expiry'])} ATM IV",
                f"{expiry_summary['atm_iv'] * 100:.1f}%",
                f"EM ±{expiry_summary['expected_move']:.0f}",
            )
    premium_check = payload.get("premium_check")
    if premium_check and premium_check["is_elevated"]:
        st.info(
            f"Front expiry IV is elevated vs next expiry by {premium_check['distortion'] * 100:.1f} vol points."
        )

