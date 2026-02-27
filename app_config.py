"""
Breeze Options Trader PRO v10.0 — Configuration
All pure logic. No external dependencies.
"""

from datetime import datetime, date as _date, timedelta, timezone
from typing import Dict, List, Literal, Optional, Set
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


# ═══════════════════════════════════════════════════════════════
# NSE / BSE HOLIDAY CALENDAR — HARDCODED FALLBACK
# ═══════════════════════════════════════════════════════════════
# ⚠️  THIS SET IS NO LONGER THE PRIMARY SOURCE OF TRUTH.
#
# The app now fetches holidays dynamically from the NSE API via
# holiday_calendar.py, which caches results in SQLite.  The set
# below is used ONLY as a fallback when the NSE API is unreachable.
#
# You do NOT need to update this set every year — holiday_calendar.py
# will fetch the live NSE calendar automatically and cache it.
#
# If you want to force-add a holiday that NSE hasn't published yet,
# add it here AND it will be picked up by is_nse_holiday() as a fallback.
#
# Rule: when an index options/futures expiry day falls on a holiday,
#       NSE moves the expiry to the PREVIOUS trading day.
#
# NOTE: 2025-10-02 appears once (duplicate removed from original spec).
NSE_HOLIDAYS_2025_2026: Set[str] = {
    # ── 2025 ──────────────────────────────────────────────────
    "2025-01-14",   # Makar Sankranti
    "2025-01-26",   # Republic Day
    "2025-02-26",   # Mahashivratri
    "2025-03-14",   # Holi
    "2025-03-31",   # Id-ul-Fitr (Ramadan Eid)
    "2025-04-10",   # Shri Mahavir Jayanti
    "2025-04-14",   # Dr. B.R. Ambedkar Jayanti
    "2025-04-18",   # Good Friday
    "2025-05-01",   # Maharashtra Day
    "2025-08-15",   # Independence Day
    "2025-08-27",   # Ganesh Chaturthi
    "2025-10-02",   # Mahatma Gandhi Jayanti / Dussehra
    "2025-10-20",   # Diwali Laxmi Puja
    "2025-10-21",   # Diwali Balipratipada
    "2025-10-24",   # Diwali (extra)
    "2025-11-05",   # Gurunanak Jayanti
    "2025-12-25",   # Christmas
    # ── 2026 (verify against NSE/BSE circulars) ───────────────
    "2026-01-14",   # Makar Sankranti
    "2026-01-26",   # Republic Day
    "2026-03-03",   # Maha Shivratri  ← NIFTY/FINNIFTY expiry week!
    "2026-03-13",   # Holi
    "2026-03-20",   # Gudi Padwa / Ugadi
    "2026-03-30",   # Id-ul-Fitr
    "2026-04-02",   # Ram Navami / Good Friday
    "2026-04-14",   # Dr. B.R. Ambedkar Jayanti  ← NIFTY/FINNIFTY expiry!
    "2026-04-17",   # Good Friday
    "2026-05-01",   # Maharashtra Day
    "2026-06-08",   # Id-ul-Adha (Bakrid)
    "2026-08-15",   # Independence Day
    "2026-10-02",   # Mahatma Gandhi Jayanti
    "2026-11-12",   # Diwali / Gurunanak Jayanti
    "2026-12-25",   # Christmas
}


def is_nse_holiday(d: "_date") -> bool:  # type: ignore[name-defined]
    """
    Return True if *d* is an NSE market holiday.

    Delegates to holiday_calendar (dynamic, NSE-API-backed) with automatic
    fallback to the hardcoded NSE_HOLIDAYS_2025_2026 set below.
    The dynamic module is imported lazily so that app_config remains
    side-effect-free at module level.
    """
    try:
        from holiday_calendar import is_holiday as _dyn_is_holiday
        return _dyn_is_holiday(d)
    except Exception:
        # If holiday_calendar is unavailable for any reason, use hardcoded set
        return d.isoformat() in NSE_HOLIDAYS_2025_2026


def is_trading_day(d: "_date") -> bool:  # type: ignore[name-defined]
    """Return True if *d* is a weekday that is NOT a known NSE holiday."""
    return d.weekday() < 5 and not is_nse_holiday(d)


def prev_trading_day(d: "_date", max_lookback: int = 7) -> "_date":  # type: ignore[name-defined]
    """Return the nearest previous trading day before (and not including) *d*."""
    candidate = d - timedelta(days=1)
    for _ in range(max_lookback):
        if is_trading_day(candidate):
            return candidate
        candidate -= timedelta(days=1)
    return candidate   # fallback — should never reach here


def adjust_expiry_for_holiday(expiry: "_date") -> "_date":  # type: ignore[name-defined]
    """
    Apply NSE expiry-advance rule:

    If the natural expiry date falls on a market holiday (or weekend —
    though the raw scheduler already avoids weekends), roll back to the
    nearest previous trading day.

    Example: 2026-03-03 (Tuesday, Maha Shivratri holiday)
             → 2026-03-02 (Monday, normal trading day)
    """
    adjusted = expiry
    for _ in range(7):          # safety: never loop more than a week back
        if is_trading_day(adjusted):
            return adjusted
        adjusted -= timedelta(days=1)
    return adjusted             # fallback



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
    Return the next *count* weekly expiry dates for the instrument,
    with NSE holiday adjustment applied to every date.

    Holiday rule (NSE circular):
      If the natural expiry day (e.g. Tuesday for NIFTY) is a market
      holiday, the exchange moves the expiry to the PREVIOUS trading day.
      Example: 2026-03-03 (Tuesday, Maha Shivratri) -> 2026-03-02 (Monday).

    Additional rules:
    - If today IS the (adjusted) expiry day AND market still open (<15:30),
      today is included as expiries[0].
    - If today IS the (adjusted) expiry day AND market closed (>=15:30),
      skip to next natural expiry week.
    - Duplicate dates are deduplicated; extra weeks are appended.
    - Returns YYYY-MM-DD strings.
    """
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []

    target_day = DAY_NUM[inst.expiry_day]
    now = _now_ist()
    today = now.date()
    market_closed_today = now.hour > 15 or (now.hour == 15 and now.minute >= 30)

    days_ahead = (target_day - now.weekday()) % 7
    if days_ahead == 0 and market_closed_today:
        days_ahead = 7   # natural expiry today but market closed, roll to next week

    base_natural = (now + timedelta(days=days_ahead)).date()
    results: List[str] = []
    seen: set = set()

    # Scan enough weeks to collect *count* distinct adjusted dates
    for i in range(count + 14):
        natural = base_natural + timedelta(weeks=i)
        adjusted = adjust_expiry_for_holiday(natural)

        # Skip past dates (adjustment may pull date before today)
        if adjusted < today:
            continue
        # Skip if adjusted == today but market already closed
        if adjusted == today and market_closed_today:
            continue

        key = adjusted.isoformat()
        if key not in seen:
            seen.add(key)
            results.append(key)
        if len(results) >= count:
            break

    return results

def get_monthly_expiries(instrument_name: str, count: int = 3) -> List[str]:
    """
    Get the next *count* monthly expiry dates (last expiry-day of each month),
    with NSE holiday adjustment applied.

    Holiday rule: if the last expiry-day of the month is a holiday, the
    expiry is moved to the PREVIOUS trading day.
    """
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return []
    target_day = DAY_NUM[inst.expiry_day]
    now = _now_ist()
    today = now.date()
    result = []
    seen: set = set()
    for m in range(count + 6):   # scan extra months to handle edge cases
        month = (now.month + m - 1) % 12 + 1
        year = now.year + (now.month + m - 1) // 12
        if month == 12:
            last_day = _date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = _date(year, month + 1, 1) - timedelta(days=1)
        # Last occurrence of target_day in this month
        diff = (last_day.weekday() - target_day) % 7
        natural_expiry = last_day - timedelta(days=diff)
        # Apply holiday adjustment
        adjusted = adjust_expiry_for_holiday(natural_expiry)
        if adjusted < today:
            continue
        key = adjusted.isoformat()
        if key not in seen:
            seen.add(key)
            result.append(key)
        if len(result) >= count:
            break
    return result

def get_natural_expiry_for(instrument_name: str, adjusted_expiry: str) -> Optional[str]:
    """
    Given an adjusted expiry date (YYYY-MM-DD) that was returned by
    get_next_expiries(), return the *natural* (pre-holiday) expiry date
    if the two differ — or None if they are the same.

    This is used by the UI to display an advisory banner when the expiry
    shown to the user is different from the underlying calendar date.

    Example:
      natural  = 2026-03-03 (Tuesday, Maha Shivratri holiday)
      adjusted = 2026-03-02 (Monday)
      → returns "2026-03-03"
    """
    try:
        inst = get_instrument(instrument_name)
    except KeyError:
        return None

    target_day = DAY_NUM[inst.expiry_day]
    try:
        adj = _date.fromisoformat(adjusted_expiry)
    except ValueError:
        return None

    # The natural expiry is the next occurrence of target_day on or after adj
    # (it could be adj itself if not adjusted, or adj + 1..6 days forward)
    for delta in range(7):
        candidate = adj + timedelta(days=delta)
        if candidate.weekday() == target_day:
            natural_iso = candidate.isoformat()
            if natural_iso != adjusted_expiry:
                return natural_iso
            return None   # same date — no adjustment was made
    return None


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
    """Return True if NSE market is currently open.

    Checks: weekday, not a public holiday, and within trading hours.
    """
    now = _now_ist()
    today = now.date()
    if now.weekday() >= 5:           # weekend
        return False
    if is_nse_holiday(today):        # public holiday
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
    """Return rich market status dict, including public-holiday awareness."""
    now = _now_ist()
    today = now.date()

    if now.weekday() >= 5:
        return {"status": "closed", "label": "🔴 Closed (Weekend)", "color": "red"}

    if is_nse_holiday(today):
        # Show which expiry-adjusted dates are affected if today is one
        return {
            "status": "closed",
            "label": "🔴 Market Holiday",
            "color": "red",
            "is_holiday": True,
            "holiday_date": today.isoformat(),
        }

    o  = now.replace(hour=MARKET_OPEN[0],          minute=MARKET_OPEN[1],          second=0, microsecond=0)
    c  = now.replace(hour=MARKET_CLOSE[0],         minute=MARKET_CLOSE[1],         second=0, microsecond=0)
    pc = now.replace(hour=MARKET_PRE_CLOSE[0],     minute=MARKET_PRE_CLOSE[1],     second=0, microsecond=0)
    p  = now.replace(hour=MARKET_PRE_OPEN_START[0],minute=MARKET_PRE_OPEN_START[1],second=0, microsecond=0)

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
