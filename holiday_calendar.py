"""
holiday_calendar.py — Dynamic NSE Trading Holiday Calendar
============================================================

Replaces the old static NSE_HOLIDAYS_2025_2026 set in app_config.py.

Architecture
------------
1.  On first call  → fetch trading holidays for the required year(s) from the
    NSE official API  (https://www.nseindia.com/api/holiday-master?type=trading).
2.  Cache results  → stored in the existing SQLite DB (data/breeze_trader.db)
    in a new `nse_holidays` table.  Survives app restarts.
3.  Stale-cache    → re-fetches if cache is older than _CACHE_MAX_AGE_HOURS (24 h)
    OR if a newly-requested calendar year is missing from the DB.
4.  Fallback       → if NSE API is unreachable (network error, Streamlit Cloud
    blocking, maintenance) the hardcoded FALLBACK_HOLIDAYS set is used instead.
    The app never breaks even without internet access.

Thread Safety
-------------
A module-level lock ensures only one thread fetches at a time; all others wait
and then read from the shared in-memory set.

Public API (used by app_config.py)
-----------------------------------
    is_holiday(d: date) -> bool
    get_calendar()      -> HolidayCalendar   (singleton)
    force_refresh()     -> int               (number of holidays fetched)
    get_holidays_for_year(year) -> Set[str]  (ISO date strings)
    get_status()        -> dict              (for the Settings UI)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import requests

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_NSE_HOME          = "https://www.nseindia.com"
_NSE_HOLIDAY_API   = "https://www.nseindia.com/api/holiday-master?type=trading"
_REQUEST_TIMEOUT   = 15          # seconds per HTTP call
_CACHE_MAX_AGE_H   = 24          # hours before re-fetching from NSE
_DB_PATH           = Path("data/breeze_trader.db")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Referer":         "https://www.nseindia.com/",
    "Cache-Control":   "no-cache",
}

# ── Hardcoded fallback (used when NSE API unreachable) ───────────────────────
# Source: NSE / BSE circulars for 2025-2026.
# This is the SAME set that was previously in app_config.py.
# It is only consulted when the live fetch has failed.

FALLBACK_HOLIDAYS: Set[str] = {
    # ── 2025 ──
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
    # ── 2026 ──
    "2026-01-14",   # Makar Sankranti
    "2026-01-26",   # Republic Day
    "2026-03-03",   # Maha Shivratri
    "2026-03-13",   # Holi
    "2026-03-20",   # Gudi Padwa / Ugadi
    "2026-03-30",   # Id-ul-Fitr
    "2026-04-02",   # Ram Navami / Good Friday
    "2026-04-14",   # Dr. B.R. Ambedkar Jayanti
    "2026-04-17",   # Good Friday
    "2026-05-01",   # Maharashtra Day
    "2026-06-08",   # Id-ul-Adha (Bakrid)
    "2026-08-15",   # Independence Day
    "2026-10-02",   # Mahatma Gandhi Jayanti
    "2026-11-12",   # Diwali / Gurunanak Jayanti
    "2026-12-25",   # Christmas
}


# ── DB helpers ───────────────────────────────────────────────────────────────

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS nse_holidays (
    iso_date    TEXT PRIMARY KEY,          -- YYYY-MM-DD
    description TEXT    NOT NULL DEFAULT '',
    year        INTEGER NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'nse_api',
    fetched_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nse_holidays_year ON nse_holidays(year);
"""


def _open_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=8, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_DB_SCHEMA)
    return conn


# ── NSE API fetch ─────────────────────────────────────────────────────────────

def _parse_nse_date(raw: str) -> Optional[date]:
    """Parse NSE date strings: 'DD-Mon-YYYY', 'YYYY-MM-DD', 'DD-MM-YYYY'."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _fetch_nse_api() -> Dict[str, Tuple[str, int]]:
    """
    Fetch holidays from NSE API.

    Returns
    -------
    dict  {iso_date: (description, year)}   — empty dict on any failure.

    NSE requires a live browser session cookie.  We prime it by visiting the
    homepage first, then call the holiday API.  The session object persists
    cookies across the two requests.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)

    try:
        # Step 1: prime the NSE cookie jar
        home_resp = session.get(_NSE_HOME, timeout=_REQUEST_TIMEOUT)
        home_resp.raise_for_status()
        time.sleep(0.8)   # brief pause — mimics browser behaviour
    except Exception as exc:
        log.warning("HolidayCalendar: could not reach NSE homepage: %s", exc)
        return {}

    try:
        api_resp = session.get(_NSE_HOLIDAY_API, timeout=_REQUEST_TIMEOUT)
        api_resp.raise_for_status()
        data = api_resp.json()
    except Exception as exc:
        log.warning("HolidayCalendar: NSE holiday API call failed: %s", exc)
        return {}

    # NSE returns a dict of market segments.
    # "FO" = Futures & Options (most relevant), "CM" = Cash Market.
    # We union them so no holiday is missed.
    results: Dict[str, Tuple[str, int]] = {}
    for segment in ("FO", "CM", "CD", "MF"):
        entries = data.get(segment)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            raw_date = entry.get("tradingDate") or entry.get("date") or ""
            desc     = str(entry.get("description") or entry.get("holiday") or "")
            d = _parse_nse_date(raw_date)
            if d is None:
                continue
            iso = d.isoformat()
            if iso not in results:            # FO takes priority
                results[iso] = (desc, d.year)

    log.info("HolidayCalendar: NSE API returned %d holidays", len(results))
    return results


# ── Singleton class ───────────────────────────────────────────────────────────

class HolidayCalendar:
    """
    Singleton.  Maintains an in-memory set of NSE holiday ISO date strings,
    backed by SQLite for persistence and NSE API for freshness.
    """

    _instance: Optional["HolidayCalendar"] = None
    _class_lock = threading.Lock()

    # ── construction / singleton access ──────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "HolidayCalendar":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = HolidayCalendar()
        return cls._instance

    def __init__(self) -> None:
        self._lock              = threading.Lock()
        self._holiday_set: Set[str]  = set()      # ISO dates in memory
        self._loaded_years: Set[int] = set()
        self._last_fetch_ts: float   = 0.0        # epoch seconds
        self._last_fetch_ok: bool    = False       # True if last NSE fetch succeeded
        self._fetch_count: int       = 0
        self._db_ok: bool            = False

        self._init_db()
        self._load_from_db()

    # ── DB initialisation ─────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            conn = _open_db()
            conn.close()
            self._db_ok = True
        except Exception as exc:
            log.warning("HolidayCalendar: DB init failed: %s", exc)

    # ── Load from DB ──────────────────────────────────────────────────────────

    def _load_from_db(self) -> None:
        if not self._db_ok:
            return
        try:
            conn = _open_db()
            rows = conn.execute(
                "SELECT iso_date, year, fetched_at FROM nse_holidays ORDER BY iso_date"
            ).fetchall()
            conn.close()
        except Exception as exc:
            log.warning("HolidayCalendar: DB read failed: %s", exc)
            return

        with self._lock:
            for iso_date, year, fetched_at in rows:
                self._holiday_set.add(iso_date)
                self._loaded_years.add(year)
                # Track last fetch time from DB rows
                try:
                    ts = datetime.fromisoformat(fetched_at).timestamp()
                    if ts > self._last_fetch_ts:
                        self._last_fetch_ts = ts
                        self._last_fetch_ok = True
                except Exception:
                    pass

        log.info(
            "HolidayCalendar: loaded %d holidays from DB (years: %s)",
            len(rows), sorted(self._loaded_years)
        )

    # ── Save to DB ────────────────────────────────────────────────────────────

    def _save_to_db(self, holidays: Dict[str, Tuple[str, int]], source: str = "nse_api") -> None:
        if not self._db_ok or not holidays:
            return
        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        rows = [
            (iso, desc, yr, source, now_iso)
            for iso, (desc, yr) in holidays.items()
        ]
        try:
            conn = _open_db()
            conn.executemany(
                """INSERT OR REPLACE INTO nse_holidays
                   (iso_date, description, year, source, fetched_at)
                   VALUES (?,?,?,?,?)""",
                rows,
            )
            conn.commit()
            conn.close()
            log.info("HolidayCalendar: saved %d holidays to DB", len(rows))
        except Exception as exc:
            log.warning("HolidayCalendar: DB write failed: %s", exc)

    # ── Refresh logic ─────────────────────────────────────────────────────────

    def _cache_is_stale(self, year: int) -> bool:
        """Return True if we should attempt a fresh fetch from NSE."""
        with self._lock:
            if year not in self._loaded_years:
                return True
            age_hours = (time.time() - self._last_fetch_ts) / 3600
            return age_hours >= _CACHE_MAX_AGE_H

    def _refresh(self, year: int) -> None:
        """
        Fetch from NSE API and update memory + DB.
        Called only when the cache is stale or a year is missing.
        """
        # Re-check under the instance lock to avoid duplicate fetches
        with self._lock:
            if year in self._loaded_years and \
               (time.time() - self._last_fetch_ts) / 3600 < _CACHE_MAX_AGE_H:
                return   # another thread already refreshed

        log.info("HolidayCalendar: fetching fresh data from NSE API (year=%d)", year)
        holidays = _fetch_nse_api()

        if holidays:
            self._save_to_db(holidays, source="nse_api")
            with self._lock:
                for iso, (desc, yr) in holidays.items():
                    self._holiday_set.add(iso)
                    self._loaded_years.add(yr)
                self._last_fetch_ts = time.time()
                self._last_fetch_ok = True
                self._fetch_count += 1
        else:
            # Fetch failed — seed fallback into DB for this year if missing
            log.warning(
                "HolidayCalendar: NSE fetch failed; seeding fallback for year %d", year
            )
            fallback_for_year = {
                iso: (f"(fallback) {iso}", int(iso[:4]))
                for iso in FALLBACK_HOLIDAYS
                if int(iso[:4]) == year
            }
            if fallback_for_year:
                self._save_to_db(fallback_for_year, source="fallback")
                with self._lock:
                    for iso in fallback_for_year:
                        self._holiday_set.add(iso)
                    self._loaded_years.add(year)
            with self._lock:
                self._last_fetch_ts = time.time()   # throttle: wait 24h before retry
                self._last_fetch_ok = False

    # ── Public API ────────────────────────────────────────────────────────────

    def ensure_year(self, year: int) -> None:
        """Ensure holidays for *year* are loaded; fetch from NSE if needed."""
        if self._cache_is_stale(year):
            self._refresh(year)

    def is_holiday(self, d: date) -> bool:
        """
        Return True if *d* is an NSE trading holiday.

        Order of precedence:
        1. Dynamic calendar (in-memory + DB-backed, fetched from NSE API)
        2. FALLBACK_HOLIDAYS set (hardcoded, always available)
        """
        self.ensure_year(d.year)
        iso = d.isoformat()
        with self._lock:
            if iso in self._holiday_set:
                return True
        # Always check fallback too — covers any dates NSE API may have missed
        return iso in FALLBACK_HOLIDAYS

    def get_holidays_for_year(self, year: int) -> Dict[str, str]:
        """
        Return {iso_date: description} for all holidays in *year*.
        Also includes any fallback holidays not already present.
        """
        self.ensure_year(year)
        result: Dict[str, str] = {}
        # Pull descriptions from DB
        if self._db_ok:
            try:
                conn = _open_db()
                rows = conn.execute(
                    "SELECT iso_date, description FROM nse_holidays WHERE year=? ORDER BY iso_date",
                    (year,)
                ).fetchall()
                conn.close()
                for iso, desc in rows:
                    result[iso] = desc
            except Exception:
                pass
        # Merge fallback holidays for this year
        for iso in FALLBACK_HOLIDAYS:
            if iso.startswith(str(year)) and iso not in result:
                result[iso] = "(fallback)"
        return result

    def force_refresh(self) -> Tuple[int, bool]:
        """
        Force a fresh fetch from NSE (ignores cache age).
        Returns (count_of_holidays_now_in_memory, fetch_succeeded).
        """
        with self._lock:
            self._loaded_years.clear()
            self._last_fetch_ts = 0.0
        current_year = date.today().year
        self._refresh(current_year)
        self._refresh(current_year + 1)
        with self._lock:
            return len(self._holiday_set), self._last_fetch_ok

    def get_status(self) -> dict:
        """Return a status dict for the Settings UI."""
        with self._lock:
            age_h   = (time.time() - self._last_fetch_ts) / 3600 if self._last_fetch_ts else None
            return {
                "total_holidays_in_memory": len(self._holiday_set),
                "loaded_years":             sorted(self._loaded_years),
                "last_fetch_ok":            self._last_fetch_ok,
                "last_fetch_age_hours":     round(age_h, 1) if age_h is not None else None,
                "cache_max_age_hours":      _CACHE_MAX_AGE_H,
                "nse_api_url":              _NSE_HOLIDAY_API,
                "db_path":                  str(_DB_PATH),
                "fetch_count":              self._fetch_count,
            }


# ── Module-level convenience functions (used by app_config.py) ───────────────

def get_calendar() -> HolidayCalendar:
    """Return the singleton HolidayCalendar instance."""
    return HolidayCalendar.get_instance()


def is_holiday(d: date) -> bool:
    """
    Top-level helper — returns True if *d* is an NSE trading holiday.
    Always safe to call; falls back gracefully if anything goes wrong.
    """
    try:
        return HolidayCalendar.get_instance().is_holiday(d)
    except Exception as exc:
        log.error("HolidayCalendar.is_holiday error: %s; using fallback", exc)
        return d.isoformat() in FALLBACK_HOLIDAYS


def get_holidays_for_year(year: int) -> Dict[str, str]:
    """Return {iso_date: description} for *year* (uses singleton)."""
    try:
        return HolidayCalendar.get_instance().get_holidays_for_year(year)
    except Exception:
        return {iso: "(fallback)" for iso in FALLBACK_HOLIDAYS if iso.startswith(str(year))}


def force_refresh() -> Tuple[int, bool]:
    """Force an NSE API refresh (uses singleton)."""
    return HolidayCalendar.get_instance().force_refresh()


def get_status() -> dict:
    """Return status dict for the Settings UI (uses singleton)."""
    return HolidayCalendar.get_instance().get_status()
