"""Pure helpers for option-chain page wiring and selection behavior."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

import pandas as pd


STRIKE_SELECTABLE_CHARTS = frozenset(
    {
        "OI Profile",
        "Delta OI",
        "IV Smile",
        "Compare OI",
        "Compare IV Smile",
        "Gamma",
        "Vanna",
        "Charm",
    }
)


def resolve_monitored_strike_defaults(
    state_monitored: Sequence[int],
    persisted_monitored: Sequence[int],
    all_strikes: Sequence[int],
) -> List[int]:
    preferred = list(state_monitored or persisted_monitored or [])
    allowed = {int(strike) for strike in all_strikes}
    return sorted({int(strike) for strike in preferred if int(strike) in allowed})


def resolve_selected_strike(
    selected_strike: Optional[int],
    all_strikes: Sequence[int],
    atm: float,
) -> Optional[int]:
    allowed = sorted({int(strike) for strike in all_strikes})
    if not allowed:
        return None
    if selected_strike is not None and int(selected_strike) in allowed:
        return int(selected_strike)
    atm_float = float(atm or 0.0)
    if atm_float > 0:
        return min(allowed, key=lambda strike: abs(strike - atm_float))
    return allowed[0]


def option_chain_chart_supports_selection(chart_tab: str) -> bool:
    return str(chart_tab) in STRIKE_SELECTABLE_CHARTS


def extract_dataframe_selection_rows(selection_state: Any) -> List[int]:
    selection = getattr(selection_state, "selection", None)
    if selection is not None and hasattr(selection, "rows"):
        return list(getattr(selection, "rows", []) or [])
    if isinstance(selection_state, dict):
        return list(selection_state.get("selection", {}).get("rows", []) or [])
    return []


def extract_plotly_selected_strike(selection_state: Any) -> Optional[int]:
    selection = getattr(selection_state, "selection", None)
    points = getattr(selection, "points", None) if selection is not None else None
    if points is None and isinstance(selection_state, dict):
        points = selection_state.get("selection", {}).get("points", [])
    for point in points or []:
        candidate = point.get("customdata", point.get("x")) if hasattr(point, "get") else None
        try:
            if isinstance(candidate, (list, tuple)) and candidate:
                candidate = candidate[0]
            strike = int(float(candidate))
            if strike > 0:
                return strike
        except (TypeError, ValueError):
            continue
    return None


def style_option_chain_rows(
    df: pd.DataFrame,
    selected_strike: Optional[int],
    pinned_strikes: Iterable[int] = (),
    atm: Optional[float] = None,
    max_pain: Optional[float] = None,
):
    if df.empty:
        return df
    pinned = {int(strike) for strike in pinned_strikes}
    selected = int(selected_strike) if selected_strike else None
    atm_int = int(float(atm)) if atm else None
    max_pain_int = int(float(max_pain)) if max_pain else None
    strike_col = "strike" if "strike" in df.columns else ("strike_price" if "strike_price" in df.columns else None)
    if strike_col is None:
        return df

    def _style_row(row: pd.Series) -> List[str]:
        try:
            strike = int(float(row[strike_col]))
        except (TypeError, ValueError):
            return [""] * len(row)
        style = ""
        if strike == max_pain_int:
            style = "background-color: rgba(148, 103, 189, 0.12);"
        if strike == atm_int:
            style = "background-color: rgba(255, 193, 7, 0.14);"
        if strike in pinned:
            style = "background-color: rgba(13, 110, 253, 0.10);"
        if strike == selected:
            style = "background-color: rgba(23, 162, 184, 0.22); font-weight: 700;"
        return [style] * len(row)

    return df.style.apply(_style_row, axis=1)


def build_replay_delta_oi_frame(change_df: pd.DataFrame, fallback_df: pd.DataFrame) -> pd.DataFrame:
    if change_df is not None and not change_df.empty and {"strike", "option_type", "open_interest_change"}.issubset(change_df.columns):
        frame = change_df.copy()
        frame["strike_price"] = pd.to_numeric(frame["strike"], errors="coerce").fillna(0)
        frame["right"] = frame["option_type"].map({"CE": "Call", "PE": "Put"}).fillna(frame["option_type"])
        frame["oi_change"] = pd.to_numeric(frame["open_interest_change"], errors="coerce").fillna(0.0)
        return frame[["strike_price", "right", "oi_change"]]
    if fallback_df is None or fallback_df.empty:
        return pd.DataFrame(columns=["strike_price", "right", "oi_change"])
    cols = [col for col in ["strike_price", "right", "oi_change"] if col in fallback_df.columns]
    return fallback_df[cols].copy() if cols else pd.DataFrame(columns=["strike_price", "right", "oi_change"])
