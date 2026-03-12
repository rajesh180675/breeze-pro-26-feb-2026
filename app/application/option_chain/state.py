"""Session-state helpers for the option-chain workspace."""

from __future__ import annotations

from typing import Any, Dict, MutableMapping

STATE_KEY = "option_chain_workspace_state"

DEFAULT_STATE = {
    "selected_strike": None,
    "pinned_strikes": [],
    "selected_chart": "oi_profile",
    "compare_expiries": [],
    "normalization_mode": "absolute",
    "replay_mode": False,
    "replay_timestamp": None,
    "change_window": "Since Open",
    "show_only_liquid": False,
    "show_only_unusual": False,
    "monitored_strikes": [],
    "visible_strike_window": None,
    "sticky_atm": True,
}


def ensure_option_chain_state(session_state: MutableMapping[str, Any]) -> Dict[str, Any]:
    state = dict(DEFAULT_STATE)
    state.update(session_state.get(STATE_KEY, {}))
    session_state[STATE_KEY] = state
    return state


def update_option_chain_state(session_state: MutableMapping[str, Any], **updates: Any) -> Dict[str, Any]:
    state = ensure_option_chain_state(session_state)
    state.update(updates)
    session_state[STATE_KEY] = state
    return state

