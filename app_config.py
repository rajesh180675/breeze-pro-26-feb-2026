"""
Breeze Options Trader PRO v10.0 — Configuration
All pure logic. No external dependencies.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional
from dataclasses import dataclass
import pytz

IST = pytz.timezone("Asia/Kolkata")

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
MAX_LOTS_PER_ORDER = 1000
MIN_LOTS_PER_ORDER = 1
RISK_FREE_RATE = 0.065
DAYS_PER_YEAR = 365
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
        "NIFTY", "NIFTY", "NFO", 75, 0.05, 50, "Thursday",
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
        "SENSEX", "BSESEN", "BFO", 10, 0.05, 100, "Friday",
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
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    target_day = DAY_NUM[inst.expiry_day]
    now = datetime.now(IST)
    days_ahead = (target_day - now.weekday()) % 7
    # If today is expiry day but market is closed, go to next week
    if days_ahead == 0 and now.hour >= 15 and now.minute >= 30:
        days_ahead = 7
    base = now + timedelta(days=days_ahead) if days_ahead > 0 else now
    expiries = [(base + timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(count)]
    return expiries


def get_monthly_expiries(instrument_name: str, count: int = 3) -> List[str]:
    """Get last thursday (or expiry day) of each month."""
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    target_day = DAY_NUM[inst.expiry_day]
    now = datetime.now(IST)
    result = []
    for m in range(count):
        month = (now.month + m - 1) % 12 + 1
        year = now.year + (now.month + m - 1) // 12
        # Last day of month
        if month == 12:
            last_day = datetime(year, month, 31)
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
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
    c = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0)
    return o <= now <= c


def get_market_status() -> dict:
    """Return rich market status dict."""
    now = datetime.now(IST)
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
