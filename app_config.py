"""
Breeze Options Trader PRO v10.0 — Configuration
All pure logic. No external dependencies.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional
from dataclasses import dataclass

# Timezone setup: prefer pytz when available; fall back to stdlib zoneinfo (Python 3.9+)
try:
    import pytz as _pytz_mod  # type: ignore[import]
    IST = _pytz_mod.timezone("Asia/Kolkata")
    def _now_ist() -> datetime:
        return datetime.now(_pytz_mod.timezone("Asia/Kolkata"))
except ImportError:
    try:
        from zoneinfo import ZoneInfo as _ZoneInfo
        IST = _ZoneInfo("Asia/Kolkata")
        def _now_ist() -> datetime:  # type: ignore[misc]
            return datetime.now(tz=_ZoneInfo("Asia/Kolkata"))
    except Exception:
        # Last resort: use UTC offset +5:30
        IST = timezone(timedelta(hours=5, minutes=30))
        def _now_ist() -> datetime:  # type: ignore[misc]
            return datetime.now(tz=timezone(timedelta(hours=5, minutes=30)))

# ─── Market hours ──────────────────────────────────────────────
MARKET_PRE_OPEN_START = (9, 0)
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
MARKET_PRE_CLOSE = (15, 15)

# ─── Session management ────────────────────────────────────────
SESSION_TIMEOUT_SECONDS = 28800   # 8 hours
SESSION_WARNING_SECONDS = 25200   # 7 hours

# ─── Cache TTLs ────────────────────────────────────────────────
OC_CACHE_TTL_SECONDS = 30
QUOTE_CACHE_TTL_SECONDS = 5
POSITION_CACHE_TTL_SECONDS = 10
FUNDS_CACHE_TTL_SECONDS = 60
SPOT_CACHE_TTL_SECONDS = 15
HISTORICAL_CACHE_TTL_SECONDS = 300

# ─── Limits ────────────────────────────────────────────────────
MAX_ACTIVITY_LOG_ENTRIES = 200
MAX_LOTS_PER_ORDER = 900    # NSE limit for NIFTY futures per order
MIN_LOTS_PER_ORDER = 1
RISK_FREE_RATE = 0.065      # Approximate Indian risk-free rate (6.5%)
DAYS_PER_YEAR = 365.0
TRADING_DAYS_PER_YEAR = 252  # NSE trading days per year

# ─── Futures lot sizes (NSE — verify against latest NSE circulars) ────────
FUTURES_LOT_SIZES: Dict[str, int] = {
    "NIFTY":      75,
    "BANKNIFTY":  30,
    "FINNIFTY":   40,
    "MIDCPNIFTY": 75,
    "SENSEX":     10,
    "BANKEX":     15,
}
MAX_WATCHLIST_ITEMS = 20

# ─── Auto-refresh ──────────────────────────────────────────────
AUTO_REFRESH_INTERVALS = [10, 15, 30, 60, 120]   # seconds
DEFAULT_REFRESH_INTERVAL = 30

# ─── Portfolio risk limits ─────────────────────────────────────
DEFAULT_MAX_PORTFOLIO_LOSS = 50000   # INR
DEFAULT_MAX_DELTA = 500
DEFAULT_MARGIN_WARNING_PCT = 75
DEFAULT_MARGIN_CRITICAL_PCT = 90


@dataclass(frozen=True)
class InstrumentConfig:
    display_name: str
    api_code: str
    exchange: Literal['NFO', 'BFO']
    lot_size: int
    tick_size: float
    strike_gap: int
    expiry_day: Literal['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    description: str
    segment: str = "index"          # index / stock
    spot_code: str = ""
    spot_exchange: str = ""
    min_strike: int = 0
    max_strike: int = 999999
    weekly_expiry: bool = True
    monthly_expiry: bool = True
    color: str = "#1f77b4"          # chart color


INSTRUMENTS: Dict[str, InstrumentConfig] = {
    "NIFTY": InstrumentConfig(
        "NIFTY", "NIFTY", "NFO", 65, 0.05, 50, "Tuesday",
        "NIFTY 50 Index Options", "index", "NIFTY", "NSE",
        15000, 30000, True, True, "#1f77b4"),
    "BANKNIFTY": InstrumentConfig(
        "BANKNIFTY", "BANKNIFTY", "NFO", 15, 0.05, 100, "Wednesday",
        "Bank NIFTY Index Options", "index", "CNXBAN", "NSE",
        30000, 60000, True, True, "#ff7f0e"),
    "FINNIFTY": InstrumentConfig(
        "FINNIFTY", "FINNIFTY", "NFO", 40, 0.05, 50, "Tuesday",
        "NIFTY Financial Services Options", "index", "FINNIFTY", "NSE",
        15000, 30000, True, True, "#2ca02c"),
    "MIDCPNIFTY": InstrumentConfig(
        "MIDCPNIFTY", "MIDCPNIFTY", "NFO", 75, 0.05, 25, "Monday",
        "NIFTY Midcap Select Options", "index", "MIDCPNIFTY", "NSE",
        8000, 20000, True, True, "#d62728"),
    "SENSEX": InstrumentConfig(
        "SENSEX", "BSESEN", "BFO", 20, 0.05, 100, "Thursday",
        "BSE SENSEX Options", "index", "BSESEN", "BSE",
        50000, 100000, True, True, "#9467bd"),
    "BANKEX": InstrumentConfig(
        "BANKEX", "BANKEX", "BFO", 15, 0.05, 100, "Monday",
        "BSE BANKEX Options", "index", "BANKEX", "BSE",
        40000, 80000, True, True, "#8c564b"),
}

DAY_NUM = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4}


def get_instrument(name: str) -> InstrumentConfig:
    if name not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {name}")
    return INSTRUMENTS[name]


def get_next_expiries(instrument_name: str, count: int = 6) -> List[str]:
    """
    Return the next  weekly expiry dates for the given instrument.

    Rules:
    - If today IS the expiry day AND market is still open (before 15:30 IST),
      today is included as expiries[0].
    - If today IS the expiry day AND market is closed (>= 15:30 IST),
      skip to next week.
    - Always returns clean calendar dates (no time component) in YYYY-MM-DD format.
    """
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    target_day = DAY_NUM[inst.expiry_day]
    now = _now_ist()
    days_ahead = (target_day - now.weekday()) % 7

    # If today is expiry day: include today if market open, else jump to next week
    if days_ahead == 0:
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            days_ahead = 7  # market closed — skip to next week

    # Compute a clean date (no time) for the base expiry
    base_date = (now + timedelta(days=days_ahead)).date()
    expiries = [
        (base_date + timedelta(weeks=i)).strftime("%Y-%m-%d")
        for i in range(count)
    ]
    return expiries


def get_monthly_expiries(instrument_name: str, count: int = 3) -> List[str]:
    """Get last thursday (or expiry day) of each month."""
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    target_day = DAY_NUM[inst.expiry_day]
    now = _now_ist()
    result = []
    for m in range(count):
        month = (now.month + m - 1) % 12 + 1
        year = now.year + (now.month + m - 1) // 12
        # Last day of month — use first day of NEXT month minus 1 day, works for all months
        if month == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1) - timedelta(days=1)
        # Go back to last expiry day
        diff = (last_day.weekday() - target_day) % 7
        expiry = last_day - timedelta(days=diff)
        result.append(expiry.strftime("%Y-%m-%d"))
    return result


def api_code_to_display(api_code: str) -> str:
    if not api_code:
        return ""
    for name, config in INSTRUMENTS.items():
        if config.api_code == api_code:
            return name
    return api_code


def display_to_api_code(display_name: str) -> str:
    if display_name in INSTRUMENTS:
        return INSTRUMENTS[display_name].api_code
    return display_name


def normalize_option_type(option_str) -> str:
    if option_str is None or option_str == "":
        return "N/A"
    s = str(option_str).strip().lower()
    if not s:
        return "N/A"
    if s in ('call', 'ce', 'c'):
        return 'CE'
    elif s in ('put', 'pe', 'p'):
        return 'PE'
    return str(option_str).upper()


def is_option_position(position: dict) -> bool:
    product_type = str(position.get("product_type", "")).lower()
    if product_type == "options":
        return True
    segment = str(position.get("segment", "")).lower()
    if segment == "fno" and position.get("right") is not None:
        return True
    return False


def is_equity_position(position: dict) -> bool:
    segment = str(position.get("segment", "")).lower()
    product_type = str(position.get("product_type", "")).lower()
    if segment == "equity" or product_type in ("easymargin", "cash", "delivery", "margin"):
        return True
    return False


def validate_strike(instrument_name: str, strike: int) -> bool:
    try:
        inst = get_instrument(instrument_name)
        return inst.min_strike <= strike <= inst.max_strike and strike % inst.strike_gap == 0
    except KeyError:
        return False


def is_market_open() -> bool:
    now = _now_ist()
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
    c = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0)
    return o <= now <= c


def is_pre_market() -> bool:
    """Return True during NSE pre-open session: 9:00 AM – 9:15 AM IST, Mon–Fri."""
    now = _now_ist()
    if now.weekday() >= 5:          # Saturday = 5, Sunday = 6
        return False
    pre_open  = now.replace(hour=MARKET_PRE_OPEN_START[0], minute=MARKET_PRE_OPEN_START[1], second=0, microsecond=0)
    pre_close = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
    return pre_open <= now < pre_close


def get_market_status() -> dict:
    """Return rich market status dict."""
    now = _now_ist()
    if now.weekday() >= 5:
        return {"status": "closed", "label": "🔴 Closed (Weekend)", "color": "red"}
    o = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
    c = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0)
    pc = now.replace(hour=MARKET_PRE_CLOSE[0], minute=MARKET_PRE_CLOSE[1], second=0, microsecond=0)
    p = now.replace(hour=MARKET_PRE_OPEN_START[0], minute=MARKET_PRE_OPEN_START[1], second=0, microsecond=0)
    if now < p:
        secs = int((p - now).total_seconds())
        return {"status": "pre_market", "label": "🟡 Pre-Market", "color": "yellow",
                "countdown": secs, "next": "Market Open"}
    if now < o:
        secs = int((o - now).total_seconds())
        return {"status": "pre_open", "label": "🟠 Pre-Open", "color": "orange",
                "countdown": secs, "next": "Market Open"}
    if now <= pc:
        secs = int((c - now).total_seconds())
        return {"status": "open", "label": "🟢 Market Open", "color": "green",
                "countdown": secs, "next": "Market Close"}
    if now <= c:
        secs = int((c - now).total_seconds())
        return {"status": "pre_close", "label": "🟠 Pre-Close", "color": "orange",
                "countdown": secs, "next": "Market Close"}
    return {"status": "closed", "label": "🔴 Closed", "color": "red"}


class ErrorMessages:
    NOT_CONNECTED = "Not connected to Breeze API"
    CONNECTION_FAILED = "Failed to connect: {error}"
    SESSION_EXPIRED = "Session has expired. Please reconnect"
    ORDER_FAILED = "Order placement failed: {error}"
    CANCEL_FAILED = "Order cancellation failed: {error}"
    MODIFY_FAILED = "Order modification failed: {error}"
    FETCH_FAILED = "Failed to fetch data: {error}"
