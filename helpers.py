"""
Helpers — type conversion, API response parsing, option chain processing, formatting.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Any, Dict, List
import logging

import app_config as C
from analytics import calculate_greeks, estimate_implied_volatility

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# SAFE CONVERTERS
# ═══════════════════════════════════════════════════════════════

def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '').strip()
        return int(float(value))
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '').strip()
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def safe_background_gradient(df: pd.DataFrame, **kwargs):
    """Apply a gradient style when optional matplotlib support is available."""
    try:
        styled = df.style.background_gradient(**kwargs)
        # Force pandas to resolve style dependencies now so missing optional
        # packages fall back before Streamlit tries to render the Styler.
        styled._compute()
        return styled
    except (ImportError, ModuleNotFoundError) as exc:
        log.warning("background gradient unavailable: %s", exc)
        return df


# ═══════════════════════════════════════════════════════════════
# API RESPONSE PARSER
# ═══════════════════════════════════════════════════════════════

class APIResponse:
    def __init__(self, raw_response: Dict[str, Any]):
        self.raw = raw_response
        self.success = raw_response.get("success", False)
        self.message = raw_response.get("message", "")
        self._data = raw_response.get("data", {})
        self._success_data = self._data.get("Success") if isinstance(self._data, dict) else None

    @property
    def data(self) -> Dict:
        if not self.success:
            return {}
        if isinstance(self._success_data, dict):
            return self._success_data
        if isinstance(self._success_data, list) and self._success_data:
            return self._success_data[0] if isinstance(self._success_data[0], dict) else {}
        return self._data if isinstance(self._data, dict) else {}

    @property
    def items(self) -> List[Dict]:
        if not self.success:
            return []
        if isinstance(self._success_data, list):
            return [i for i in self._success_data if isinstance(i, dict)]
        if isinstance(self._success_data, dict):
            return [self._success_data]
        return []

    def get(self, key, default=None):
        return self.data.get(key, default)


# ═══════════════════════════════════════════════════════════════
# FUNDS
# ═══════════════════════════════════════════════════════════════

def parse_funds(response: Dict) -> Dict[str, float]:
    parsed = APIResponse(response)
    d = parsed.data
    return {
        "total_balance": safe_float(d.get("total_bank_balance", 0)),
        "allocated_equity": safe_float(d.get("allocated_equity", 0)),
        "allocated_fno": safe_float(d.get("allocated_fno", 0)),
        "unallocated": safe_float(d.get("unallocated_balance", 0)),
        "block_equity": safe_float(d.get("block_by_trade_equity", 0)),
        "block_fno": safe_float(d.get("block_by_trade_fno", 0)),
    }


# ═══════════════════════════════════════════════════════════════
# POSITION LOGIC
# ═══════════════════════════════════════════════════════════════

def detect_position_type(position: Dict) -> str:
    action = safe_str(position.get("action")).lower()
    if action == "sell":
        return "short"
    if action == "buy":
        return "long"
    for f in ("position_type", "segment"):
        v = safe_str(position.get(f)).lower()
        if "short" in v or "sell" in v:
            return "short"
        if "long" in v or "buy" in v:
            return "long"
    sell_q = safe_int(position.get("sell_quantity", 0))
    buy_q = safe_int(position.get("buy_quantity", 0))
    if sell_q > buy_q:
        return "short"
    if buy_q > sell_q:
        return "long"
    qty = safe_int(position.get("quantity", 0))
    if qty < 0:
        return "short"
    return "long"


def get_closing_action(position_type: str) -> str:
    return "buy" if position_type == "short" else "sell"


def calculate_pnl(position_type: str, avg_price: float,
                  current_price: float, quantity: int) -> float:
    qty = abs(quantity)
    if position_type == "short":
        return (avg_price - current_price) * qty
    return (current_price - avg_price) * qty


def get_pnl_color(pnl: float) -> str:
    return "#28a745" if pnl >= 0 else "#dc3545"


def enrich_positions(positions: list) -> list:
    """Add computed fields to positions list."""
    enriched = []
    for p in positions:
        pt = detect_position_type(p)
        qty = abs(safe_int(p.get("quantity", 0)))
        avg = safe_float(p.get("average_price", 0))
        ltp = safe_float(p.get("ltp", avg))
        pnl = calculate_pnl(pt, avg, ltp, qty)
        pnl_pct = ((ltp - avg) / avg * 100) if avg > 0 else 0
        if pt == "short":
            pnl_pct = -pnl_pct
        enriched.append({
            **p,
            "_pt": pt,
            "_qty": qty,
            "_avg": avg,
            "_ltp": ltp,
            "_pnl": pnl,
            "_pnl_pct": pnl_pct,
            "_close": get_closing_action(pt),
        })
    return enriched


# ═══════════════════════════════════════════════════════════════
# OPTION CHAIN
# ═══════════════════════════════════════════════════════════════

NUMERIC_COLS = [
    "strike_price", "ltp", "best_bid_price", "best_offer_price",
    "open", "high", "low", "close", "volume", "open_interest",
    "ltp_percent_change", "oi_change", "iv", "bid_qty", "offer_qty"
]


def process_option_chain(raw_data: Dict) -> pd.DataFrame:
    from option_chain_utils import process_option_chain as _process_option_chain

    return _process_option_chain(raw_data)


def create_pivot_table(df: pd.DataFrame) -> pd.DataFrame:
    from option_chain_utils import create_pivot_table as _create_pivot_table

    return _create_pivot_table(df)


def calculate_pcr(df: pd.DataFrame) -> float:
    from option_chain_metrics import calculate_pcr as _calculate_pcr

    return _calculate_pcr(df)


def calculate_max_pain(df: pd.DataFrame) -> int:
    from option_chain_metrics import calculate_max_pain as _calculate_max_pain

    return _calculate_max_pain(df)


def estimate_atm_strike(df: pd.DataFrame, spot: float = 0.0) -> float:
    from option_chain_utils import estimate_atm_strike as _estimate_atm_strike

    return _estimate_atm_strike(df, spot=spot)


def add_greeks_to_chain(df: pd.DataFrame, spot_price: float, expiry_date: str) -> pd.DataFrame:
    if df.empty:
        return df
    try:
        expiry = datetime.strptime(expiry_date[:10], "%Y-%m-%d")
        tte = max((expiry - datetime.now()).days / C.DAYS_PER_YEAR, 0.001)
    except Exception:
        tte = 0.05
    greeks_list = []
    computed_iv_values = []
    for _, row in df.iterrows():
        strike = row.get("strike_price", 0)
        ot = C.normalize_option_type(row.get("right"))
        ltp = row.get("ltp", 0)
        iv_display_value = row.get("iv", np.nan)
        if ot in ("CE", "PE") and strike > 0 and spot_price > 0 and ltp > 0:
            try:
                iv_raw = row.get("iv", 0)
                iv = iv_raw / 100 if iv_raw > 1 else (
                    estimate_implied_volatility(ltp, spot_price, strike, tte, ot)
                    if iv_raw <= 0 else iv_raw
                )
                # Task 1.4: If IV is NaN (same-day expiry), use 0 for Greeks calc
                # and mark the IV column as "—" for display
                if np.isnan(iv):
                    greeks_list.append({'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0})
                    iv_display_value = np.nan
                else:
                    greeks_list.append(calculate_greeks(spot_price, strike, tte, iv, ot))
                    if iv_raw <= 0:
                        iv_display_value = iv
            except Exception:
                greeks_list.append({'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0})
                iv_display_value = np.nan
        else:
            greeks_list.append({'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0})
        computed_iv_values.append(iv_display_value)
    out = pd.concat([df.reset_index(drop=True), pd.DataFrame(greeks_list)], axis=1)
    out["iv"] = pd.Series(computed_iv_values, index=out.index)
    out["iv"] = out["iv"].apply(lambda v: "—" if pd.isna(v) else v)
    return out


# ═══════════════════════════════════════════════════════════════
# FORMATTING
# ═══════════════════════════════════════════════════════════════

def get_market_status() -> str:
    ms = C.get_market_status()
    return ms["label"]


def format_currency(value: float) -> str:
    av = abs(value)
    sign = "-" if value < 0 else ""
    if av >= 1e7:
        return f"{sign}₹{av / 1e7:.2f}Cr"
    if av >= 1e5:
        return f"{sign}₹{av / 1e5:.2f}L"
    if av >= 1e3:
        return f"{sign}₹{av / 1e3:.1f}K"
    return f"{sign}₹{av:.2f}"


def format_number(value: float, decimals: int = 0) -> str:
    """Format number with Indian comma system."""
    if abs(value) >= 1e7:
        return f"{value / 1e7:.2f}Cr"
    if abs(value) >= 1e5:
        return f"{value / 1e5:.2f}L"
    return f"{value:,.{decimals}f}"


def format_expiry(date_str: str) -> str:
    if not date_str:
        return "—"
    date_str = str(date_str).strip()
    if not date_str or date_str in ("None", "*", "—"):
        return "—"
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%d %b %Y (%A)")
        except ValueError:
            continue
    return date_str


def format_expiry_short(date_str: str) -> str:
    if not date_str:
        return "—"
    date_str = str(date_str).strip()
    if not date_str or date_str in ("None", "*", "—"):
        return "—"
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%d %b")
        except ValueError:
            continue
    return date_str


def calculate_days_to_expiry(expiry_date: str) -> int:
    """
    Parse expiry date in any common format and return calendar days remaining.

    Supports:
      - YYYY-MM-DD            (e.g. "2026-03-04")
      - DD-Mon-YYYY           (e.g. "04-Mar-2026") — Breeze API response format
      - DD-Month-YYYY         (e.g. "04-March-2026")
      - YYYY-MM-DDTHH:MM:SS   (e.g. "2026-03-04T00:00:00.000Z")

    BUG FIX: Previous code sliced both the date string AND the format pattern
    to the same length [:10], which corrupted "DD-Mon-YYYY" strings to "DD-Mon-YYY"
    and always returned 0 for Breeze-formatted dates.
    """
    if not expiry_date:
        return 0
    s = expiry_date.strip()
    # Normalise ISO-8601 with timezone suffix: "2026-03-04T00:00:00.000Z" -> "2026-03-04"
    if "T" in s:
        s = s.split("T")[0].strip()
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y"]:
        try:
            expiry = datetime.strptime(s, fmt)
            # Use IST (UTC+5:30) for "today" to avoid off-by-one around midnight
            from datetime import timezone, timedelta as _td
            ist_now = datetime.now(tz=timezone(_td(hours=5, minutes=30))).date()
            return max(0, (expiry.date() - ist_now).days)
        except ValueError:
            continue
    log.warning(f"calculate_days_to_expiry: could not parse date '{expiry_date}'")
    return 0


def pnl_badge(value: float) -> str:
    color = "#28a745" if value >= 0 else "#dc3545"
    return f'<span style="color:{color};font-weight:700">{format_currency(value)}</span>'


def optimize_dataframe_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Reduce DataFrame memory usage by downcasting and categorical conversion."""
    if df is None or df.empty:
        return df

    optimized = df.copy()
    for col in optimized.select_dtypes(include=["float64"]).columns:
        optimized[col] = pd.to_numeric(optimized[col], downcast="float")
    for col in optimized.select_dtypes(include=["int64"]).columns:
        optimized[col] = pd.to_numeric(optimized[col], downcast="integer")
    for col in optimized.select_dtypes(include=["object"]).columns:
        series = optimized[col]
        if len(series) == 0:
            continue
        unique_ratio = series.nunique(dropna=False) / len(series)
        if unique_ratio < 0.1:
            optimized[col] = series.astype("category")
    return optimized
