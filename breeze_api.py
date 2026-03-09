"""
Breeze API Client v11.0

Critical fixes from v10/v11:
1. convert_to_breeze_datetime() now outputs ISO-8601 format required by ALL Breeze API calls
   - OLD (WRONG): "04-Mar-2026"      <- DD-Mon-YYYY not accepted by Breeze
   - NEW (CORRECT): "2026-03-04T06:00:00.000Z"  <- ISO-8601 required
2. _ok() now validates Breeze response Status field and surfaces API errors
3. get_option_chain_quotes / get_quotes / place_order all use correct datetime format
4. Added _to_breeze_datetime helper for order/trade list date params
5. Retry logic verified: data calls retry, order placement does NOT
6. Thread-safe with API lock
"""

import logging
import os
import sys
import time
import random
import hashlib
import threading
import json
from urllib.request import Request, urlopen
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from functools import wraps

from breeze_connect import BreezeConnect
import app_config as C

log = logging.getLogger(__name__)


def _load_production_breeze_client_class():
    """Load the production REST wrapper class from app/lib when available."""
    app_lib_path = Path(__file__).resolve().parent / "app"
    if app_lib_path.exists() and str(app_lib_path) not in sys.path:
        sys.path.insert(0, str(app_lib_path))
    try:
        from lib.breeze_client import BreezeClient  # type: ignore
        return BreezeClient
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# TRANSIENT ERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

TRANSIENT_PATTERNS = frozenset({
    "service unavailable", "gateway timeout", "bad gateway",
    "too many requests", "connection reset", "connection refused",
    "read timed out", "temporary failure", "503", "502", "504", "429"
})

PERMANENT_PATTERNS = frozenset({
    "invalid session", "session expired", "unauthorized",
    "invalid api key", "forbidden", "not connected"
})


def _is_transient(e: Exception) -> bool:
    msg = str(e).lower()
    return any(p in msg for p in TRANSIENT_PATTERNS)


def _is_permanent(e: Exception) -> bool:
    msg = str(e).lower()
    return any(p in msg for p in PERMANENT_PATTERNS)


# ═══════════════════════════════════════════════════════════════
# RETRY DECORATOR
# ═══════════════════════════════════════════════════════════════

def retry_api_call(max_attempts: int = 3, initial_delay: float = 0.5, backoff: float = 2.0):
    """
    Retry decorator for data-fetching calls only.
    Order placement methods must NOT use this decorator.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    if isinstance(result, dict) and not result.get("success", True):
                        msg = result.get("message", "").lower()
                        if any(p in msg for p in TRANSIENT_PATTERNS) and attempt < max_attempts:
                            log.warning(f"{func.__name__} transient response attempt {attempt}: {msg}")
                            time.sleep(delay)
                            delay *= backoff
                            continue
                    return result
                except Exception as e:
                    last_exc = e
                    if _is_permanent(e):
                        log.error(f"{func.__name__} permanent failure: {e}")
                        return {"success": False, "data": {}, "message": str(e), "error_code": "PERMANENT"}
                    if attempt < max_attempts:
                        log.warning(f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. Retry in {delay:.1f}s")
                        time.sleep(delay)
                        delay *= backoff
                    else:
                        log.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
            return {"success": False, "data": {}, "message": f"Failed after {max_attempts} attempts: {last_exc}",
                    "error_code": "MAX_RETRIES"}
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════════

class RateLimiter:
    def __init__(self, calls_per_second: float = 5.0):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_call = time.time()


# ═══════════════════════════════════════════════════════════════
# IDEMPOTENCY GUARD
# ═══════════════════════════════════════════════════════════════

class IdempotencyGuard:
    """Prevents duplicate orders within a time window."""

    def __init__(self, window: int = 60):
        self._recent: Dict[str, float] = {}
        self._window = window
        self._lock = threading.Lock()

    def make_key(self, stock_code: str, strike: int, option_type: str,
                 action: str, quantity: int) -> str:
        minute = datetime.now().strftime("%Y%m%d%H%M")
        raw = f"{stock_code}|{strike}|{option_type}|{action}|{quantity}|{minute}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check_and_reserve(self, key: str) -> bool:
        with self._lock:
            now = time.time()
            self._recent = {k: t for k, t in self._recent.items() if now - t < self._window}
            if key in self._recent:
                log.warning(f"Duplicate order blocked: {key[:8]}...")
                return False
            self._recent[key] = now
            return True

    def release(self, key: str):
        with self._lock:
            self._recent.pop(key, None)


# ═══════════════════════════════════════════════════════════════
# DATE / DATETIME CONVERSION
# ═══════════════════════════════════════════════════════════════

def convert_to_breeze_datetime(date_str: str) -> str:
    """
    Convert ANY date string to the ISO-8601 format required by ALL Breeze Connect API calls.

    Breeze Connect API requires: "YYYY-MM-DDTHH:MM:SS.000Z"
    Example: "2026-03-04T06:00:00.000Z"

    The time component T06:00:00.000Z represents 6 AM UTC (= 11:30 AM IST),
    which is the standard convention used in all official Breeze Connect examples.

    Accepts:
      - "YYYY-MM-DD"               e.g. "2026-03-04"
      - "DD-Mon-YYYY"              e.g. "04-Mar-2026"  (Breeze response format)
      - "DD-Month-YYYY"            e.g. "04-March-2026"
      - "YYYY-MM-DDTHH:MM:SS..."   e.g. "2026-03-04T00:00:00.000Z"
      - "DD/MM/YYYY"               e.g. "04/03/2026"
    """
    if not date_str or not str(date_str).strip():
        return ""
    s = str(date_str).strip()
    # If already ISO-8601 with time component, normalise to T06:00:00.000Z
    if "T" in s:
        s = s.split("T")[0].strip()
    # Now parse the date portion
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            parsed = datetime.strptime(s, fmt)
            return parsed.strftime("%Y-%m-%dT06:00:00.000Z")
        except ValueError:
            continue
    log.warning(f"convert_to_breeze_datetime: could not parse '{date_str}', passing as-is")
    return date_str


def convert_to_breeze_iso_datetime(date_str: str, end_of_day: bool = False) -> str:
    """
    Convert date string to ISO-8601 for order/trade history API calls.
    Uses T00:00:00.000Z for start-of-day, T23:59:59.000Z for end-of-day.
    """
    if not date_str or not str(date_str).strip():
        return ""
    s = str(date_str).strip()
    if "T" in s:
        s = s.split("T")[0].strip()
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            parsed = datetime.strptime(s, fmt)
            suffix = "T23:59:59.000Z" if end_of_day else "T00:00:00.000Z"
            return parsed.strftime("%Y-%m-%d") + suffix
        except ValueError:
            continue
    return date_str


class APIResponseValidator:
    """Validate and sanitize Breeze API responses."""

    @staticmethod
    def validate_quote_response(resp: Dict, expected_symbol: str = "") -> tuple[bool, str]:
        if not resp.get("success"):
            return False, str(resp.get("message", "Unknown error"))
        data = resp.get("data") or {}
        success = data.get("Success") if isinstance(data, dict) else None
        if not success:
            return False, "Empty Success in quote response"
        item = success[0] if isinstance(success, list) and success else success
        item = item if isinstance(item, dict) else {}
        ltp = APIResponseValidator.sanitize_price(item.get("ltp"), default=0.0)
        if ltp < 0:
            return False, f"Negative LTP: {ltp}"
        if ltp == 0 and C.is_market_open():
            return False, "Zero LTP during market hours (possible stale/invalid data)"
        if expected_symbol:
            symbol = str(item.get("stock_code", "") or "").strip().upper()
            if symbol and symbol != expected_symbol.strip().upper():
                return False, f"Quote symbol mismatch: expected {expected_symbol}, got {symbol}"
        return True, ""

    @staticmethod
    def validate_order_response(resp: Dict) -> tuple[bool, str]:
        if not resp.get("success"):
            return False, str(resp.get("message", "Unknown error"))
        data = resp.get("data") or {}
        success = data.get("Success") if isinstance(data, dict) else data
        if not success:
            return False, "No order ID in placement response"
        if isinstance(success, list):
            order_id = str((success[0] or {}).get("order_id", "")) if success else ""
        elif isinstance(success, dict):
            order_id = str(success.get("order_id", ""))
        else:
            order_id = str(success)
        if not order_id:
            return False, "Placement response missing order_id"
        return True, ""

    @staticmethod
    def sanitize_price(value: Any, default: float = 0.0) -> float:
        """Convert price-like value safely to non-negative float."""
        if value is None or value == "" or value == "None":
            return default
        try:
            result = float(str(value).replace(",", ""))
            return result if result >= 0 else default
        except (TypeError, ValueError):
            return default


# ═══════════════════════════════════════════════════════════════
# API CLIENT
# ═══════════════════════════════════════════════════════════════

class BreezeAPIClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.breeze: Optional[BreezeConnect] = None
        self.connected = False
        self.rate_limiter = RateLimiter(5.0)
        self.idempotency = IdempotencyGuard(60)
        self._api_lock = threading.Lock()
        self._connection_time: Optional[float] = None
        self.use_production_client = os.getenv("BREEZE_USE_PRODUCTION_CLIENT", "false").lower() in {"1", "true", "yes"}
        self._production_client = None

    def is_connected(self) -> bool:
        return self.connected and self.breeze is not None

    def _ok(self, raw_breeze_response):
        """
        Wrap a Breeze API response.

        Breeze Connect returns dicts like:
          {'Status': 200, 'Error': None, 'Success': [...]}  -> success
          {'Status': 400, 'Error': 'some error', 'Success': None}  -> API error

        We surface Breeze-level errors so callers always see them.
        """
        if isinstance(raw_breeze_response, dict):
            status = raw_breeze_response.get("Status", 200)
            error = raw_breeze_response.get("Error")
            if error or (isinstance(status, int) and status >= 400):
                msg = str(error) if error else f"Breeze API returned status {status}"
                log.error(f"Breeze API error: status={status}, error={error}")
                return {"success": False, "data": raw_breeze_response,
                        "message": msg, "error_code": f"BREEZE_{status}"}
        return {"success": True, "data": raw_breeze_response, "message": "", "error_code": None}

    def _err(self, msg, code=None):
        return {"success": False, "data": {}, "message": str(msg), "error_code": code}

    def _require_connection(self):
        if not self.connected or self.breeze is None:
            raise ConnectionError(C.ErrorMessages.NOT_CONNECTED)

    # ─── Connection ───────────────────────────────────────────

    # ── Connection timeout constant ──────────────────────────────
    _CONNECT_TIMEOUT: float = 20.0  # seconds before generate_session is declared hung

    @retry_api_call(max_attempts=2, initial_delay=1.0)
    def connect(self, session_token: str):
        breeze = BreezeConnect(api_key=self.api_key)

        # BreezeConnect.generate_session() makes a blocking HTTP call with no
        # built-in timeout.  Run it on a daemon thread so we can abort if it
        # hangs (bad token, unreachable server, etc.) rather than blocking the
        # Streamlit main thread forever and showing an infinite spinner.
        _exc: list = [None]

        def _generate():
            try:
                breeze.generate_session(
                    api_secret=self.api_secret,
                    session_token=session_token,
                )
            except Exception as e:          # noqa: BLE001
                _exc[0] = e

        t = threading.Thread(target=_generate, name="BreezeGenSession", daemon=True)
        t.start()
        t.join(timeout=self._CONNECT_TIMEOUT)

        if t.is_alive():
            # Thread is still blocked → generate_session never returned.
            raise TimeoutError(
                f"generate_session timed out after {self._CONNECT_TIMEOUT}s — "
                "verify your session token is fresh and ICICI servers are reachable."
            )
        if _exc[0] is not None:
            raise _exc[0]

        self.breeze = breeze          # assign only after success
        self.connected = True
        self._connection_time = time.time()

        if self.use_production_client:
            breeze_client_class = _load_production_breeze_client_class()
            if breeze_client_class is not None:
                os.environ["BREEZE_CLIENT_ID"] = self.api_key
                os.environ["BREEZE_CLIENT_SECRET"] = self.api_secret
                os.environ["BREEZE_SESSION_TOKEN"] = session_token
                try:
                    self._production_client = breeze_client_class(client_id=self.api_key, client_secret=self.api_secret)
                    self._production_client.authenticate()
                    log.info("Production BreezeClient bridge enabled for Streamlit UI")
                except Exception as exc:
                    self._production_client = None
                    log.warning(f"Could not initialize production BreezeClient bridge: {exc}")

        log.info("Connected to Breeze API")
        return self._ok({"message": "Connected"})

    # ─── Data fetching (retryable) ────────────────────────────

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_funds(self):
        self._require_connection()
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_funds())

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_positions(self):
        self._require_connection()
        if self._production_client is not None:
            try:
                return self._ok(self._production_client.get_positions())
            except Exception as exc:
                log.warning(f"Production client get_positions failed, falling back to SDK: {exc}")
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_portfolio_positions())

    def _fetch_one_side(self, stock_code: str, exchange: str,
                         expiry_iso: str, right: str) -> List[Dict]:
        """
        Fetch all strikes for one side (call or put) of the option chain.
        Breeze API requires an explicit right= value; it rejects right="".
        strike_price="" fetches all available strikes for that right.
        Returns list of records, or [] on error.
        """
        with self._api_lock:
            self.rate_limiter.wait()
            data = self.breeze.get_option_chain_quotes(
                stock_code=stock_code,
                exchange_code=exchange,
                product_type="options",
                expiry_date=expiry_iso,
                right=right,
                strike_price=""
            )
        log.info(
            f"_fetch_one_side {right}: status={data.get('Status') if isinstance(data, dict) else '?'} "
            f"error={data.get('Error') if isinstance(data, dict) else '?'} "
            f"records={len(data.get('Success') or []) if isinstance(data, dict) else '?'}"
        )
        if not isinstance(data, dict):
            return []
        if data.get("Error"):
            log.error(f"_fetch_one_side {right} error: {data['Error']}")
            return []
        records = data.get("Success") or []
        return records if isinstance(records, list) else []

    def get_option_chain(self, stock_code: str, exchange: str, expiry: str):
        """
        Fetch full option chain by calling Breeze twice — once for calls, once for puts —
        then merging into a single combined response.

        Root cause of previous failure:
          Breeze API returns error 500 "Either Right or Strike-Price cannot be empty"
          when right="" is passed. It requires an explicit right="call" or right="put".
          strike_price="" is accepted (fetches all strikes) only when right is explicit.
        """
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry)
        log.info(f"get_option_chain: stock={stock_code} exchange={exchange} expiry_iso={expiry_iso}")

        calls = self._fetch_one_side(stock_code, exchange, expiry_iso, "call")
        puts  = self._fetch_one_side(stock_code, exchange, expiry_iso, "put")

        all_records = calls + puts
        log.info(
            f"get_option_chain merged: {len(calls)} calls + {len(puts)} puts = {len(all_records)} total"
        )

        if not all_records:
            # Both sides empty — surface as a structured error so UI can show it
            return {
                "success": False,
                "data": {"Status": 500, "Error": "No data returned for either calls or puts", "Success": []},
                "message": "No option chain data returned from Breeze for calls or puts",
                "error_code": "EMPTY_CHAIN"
            }

        # Return in the same shape as a normal Breeze response so process_option_chain works
        combined = {"Status": 200, "Error": None, "Success": all_records}
        return {"success": True, "data": combined, "message": "", "error_code": None}

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_option_quote(self, stock_code: str, exchange: str, expiry: str,
                         strike: int, option_type: str):
        """
        Fetch LTP and market data for a specific option contract.

        This is the convenience method for callers that use human-friendly
        positional args: (stock_code, exchange, expiry, strike, option_type).
        It converts option_type (CE/PE) and expiry to Breeze API format internally.

        BUG FIX: Previously this was named get_quotes(), which was silently
        overridden by a second get_quotes() definition (lines below) that has
        a completely different signature. Any caller using the 5-arg positional
        form (risk_monitor, watchlist, sell page) was actually calling the wrong
        method and passing garbage arguments to Breeze.
        """
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry)
        right = "call" if option_type.upper() == "CE" else "put"
        log.info(f"get_option_quote: {stock_code} {exchange} {expiry_iso} {strike} {right}")
        with self._api_lock:
            self.rate_limiter.wait()
            data = self.breeze.get_quotes(
                stock_code=stock_code,
                exchange_code=exchange,
                expiry_date=expiry_iso,
                product_type="options",
                right=right,
                strike_price=str(strike)
            )
        return self._ok(data)

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_spot_price(self, stock_code: str, exchange: str):
        """
        Fetch underlying index spot price via cash market quote.
        Uses the spot_code and spot_exchange from InstrumentConfig.
        """
        self._require_connection()
        cfg = next((c for c in C.INSTRUMENTS.values() if c.api_code == stock_code), None)
        spot_code = cfg.spot_code if cfg and cfg.spot_code else stock_code
        spot_exchange = cfg.spot_exchange if cfg and cfg.spot_exchange else (
            "NSE" if exchange in ("NFO", "NSE") else "BSE"
        )
        log.info(f"get_spot_price: spot_code={spot_code} spot_exchange={spot_exchange}")
        with self._api_lock:
            self.rate_limiter.wait()
            data = self.breeze.get_quotes(
                stock_code=spot_code,
                exchange_code=spot_exchange,
                expiry_date="",
                product_type="cash",
                right="",
                strike_price=""
            )
        return self._ok(data)

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_india_vix(self):
        """
        Fetch India VIX from NSE public API.
        Returns payload shaped like other client methods:
            {"success": True, "data": {"vix": <float>}, ...}
        """
        self._require_connection()
        req = Request(
            "https://www.nseindia.com/api/allIndices",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/",
            },
        )
        with urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        for row in rows:
            if str(row.get("index", "")).strip().upper() == "INDIA VIX":
                return {
                    "success": True,
                    "data": {"vix": float(row.get("last", 0) or 0)},
                    "message": "",
                    "error_code": None,
                }
        return self._err("INDIA VIX not found in NSE response", "VIX_NOT_FOUND")

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_order_list(self, exchange="", from_date="", to_date=""):
        """Fetch order list.

        Breeze requires a non-empty exchange_code.  Default to ``NSE`` when
        called without an explicit exchange (e.g. from the warmup manager).
        If no date range is given, default to today.
        """
        self._require_connection()
        # Breeze rejects empty exchange_code — default to NSE
        exchange_code = exchange.strip() if exchange and exchange.strip() else "NSE"
        # Default date range: today
        from datetime import date as _date
        today = _date.today().isoformat()
        fd = from_date if from_date else today
        td = to_date if to_date else today
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_order_list(
                exchange_code=exchange_code,
                from_date=convert_to_breeze_iso_datetime(fd),
                to_date=convert_to_breeze_iso_datetime(td, end_of_day=True)
            ))

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_trade_list(self, exchange="", from_date="", to_date=""):
        """Fetch trade list.

        Breeze requires a non-empty exchange_code.  Default to ``NSE`` and
        today's date when called without explicit args.
        """
        self._require_connection()
        exchange_code = exchange.strip() if exchange and exchange.strip() else "NSE"
        from datetime import date as _date
        today = _date.today().isoformat()
        fd = from_date if from_date else today
        td = to_date if to_date else today
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_trade_list(
                exchange_code=exchange_code,
                from_date=convert_to_breeze_iso_datetime(fd),
                to_date=convert_to_breeze_iso_datetime(td, end_of_day=True)
            ))

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_margin(self, stock_code, exchange, expiry, strike, option_type, action, quantity):
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry)
        right = "call" if option_type.upper() == "CE" else "put"
        log.info(f"get_margin: {stock_code} {exchange} {expiry_iso} {strike} {right} {action} qty={quantity}")
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_margin(
                exchange_code=exchange,
                stock_code=stock_code,
                product_type="options",
                right=right,
                strike_price=str(strike),
                expiry_date=expiry_iso,
                quantity=str(quantity),
                action=action.lower(),
                order_type="market",
                price=""
            ))

    # ─── Order placement (NOT retried, idempotency protected) ─

    def place_order(self, stock_code, exchange, expiry, strike, option_type,
                    action, quantity, order_type="market", price=0.0):
        """
        Place an option order via Breeze Connect.

        Breeze place_order() parameters:
          product    = "options"   (NOT product_type)
          expiry_date = ISO-8601 datetime string
          right      = "call" or "put"
          strike_price = string
          price      = string (empty string for market orders)
          quantity   = string
        """
        self._require_connection()
        idem_key = self.idempotency.make_key(stock_code, strike, option_type, action, quantity)
        if not self.idempotency.check_and_reserve(idem_key):
            return self._err(
                "Duplicate order detected. Same order was placed within the last 60 seconds.",
                "DUPLICATE_ORDER"
            )
        try:
            right = "call" if option_type.upper() == "CE" else "put"
            expiry_iso = convert_to_breeze_datetime(expiry)
            price_str = str(price) if order_type.lower() == "limit" and price > 0 else ""
            log.info(
                f"PLACE ORDER: {action.upper()} {stock_code} {exchange} "
                f"strike={strike} {right} qty={quantity} "
                f"type={order_type} price={price_str} expiry={expiry_iso}"
            )
            with self._api_lock:
                self.rate_limiter.wait()
                resp = self.breeze.place_order(
                    stock_code=stock_code,
                    exchange_code=exchange,
                    product="options",
                    action=action.lower(),
                    order_type=order_type.lower(),
                    stoploss="0",
                    quantity=str(quantity),
                    price=price_str,
                    validity="day",
                    validity_date=expiry_iso,
                    disclosed_quantity="0",
                    expiry_date=expiry_iso,
                    right=right,
                    strike_price=str(strike),
                    user_remark=""
                )
            normalized = self._ok(resp)
            ok, msg = APIResponseValidator.validate_order_response(normalized)
            if not ok:
                log.warning(f"place_order response validation warning: {msg}")
            log.info(f"place_order response: {resp}")
            return normalized
        except Exception as e:
            self.idempotency.release(idem_key)
            log.error(f"Order failed: {e}", exc_info=True)
            return self._err(C.ErrorMessages.ORDER_FAILED.format(error=str(e)), "ORDER_FAILED")

    def sell_call(self, stock_code, exchange, expiry, strike, quantity,
                  order_type="market", price=0.0):
        return self.place_order(stock_code, exchange, expiry, strike, "CE", "sell",
                                quantity, order_type, price)

    def sell_put(self, stock_code, exchange, expiry, strike, quantity,
                 order_type="market", price=0.0):
        return self.place_order(stock_code, exchange, expiry, strike, "PE", "sell",
                                quantity, order_type, price)

    def square_off(
        self,
        exchange_code: str,
        product: str,
        stock_code: str,
        quantity: str,
        price: str,
        action: str,
        order_type: str,
        validity: str = "day",
        stoploss: str = "0",
        disclosed_quantity: str = "0",
        protection_percentage: str = "",
        settlement_id: str = "",
        cover_quantity: str = "",
        open_quantity: str = "",
        margin_amount: str = "",
        expiry_date: str = "",
        right: str = "",
        strike_price: str = "",
    ) -> Dict:
        """
        Square off an open position using Breeze SDK native square_off() API.

        Idempotency:
            - This method does NOT use IdempotencyGuard.
            - Do NOT retry this method automatically.
        """
        self._require_connection()
        if expiry_date:
            expiry_date = convert_to_breeze_datetime(expiry_date)

        log.info(
            f"SQUARE OFF: {action.upper()} {stock_code} {exchange_code} "
            f"strike={strike_price} {right} qty={quantity} "
            f"type={order_type} price={price!r} expiry={expiry_date}"
        )
        try:
            with self._api_lock:
                self.rate_limiter.wait()
                resp = self.breeze.square_off(
                    exchange_code=exchange_code,
                    product=product,
                    stock_code=stock_code,
                    quantity=str(quantity),
                    price=price,
                    action=action.lower(),
                    order_type=order_type.lower(),
                    validity=validity,
                    stoploss=stoploss,
                    disclosed_quantity=disclosed_quantity,
                    protection_percentage=protection_percentage,
                    settlement_id=settlement_id,
                    cover_quantity=cover_quantity,
                    open_quantity=open_quantity,
                    margin_amount=margin_amount,
                    expiry_date=expiry_date,
                    right=right.lower() if right else "",
                    strike_price=str(strike_price) if strike_price else "",
                )
            log.info(f"square_off response: {resp}")
            return self._ok(resp)
        except Exception as e:
            log.error(f"square_off failed: {e}", exc_info=True)
            return self._err(
                C.ErrorMessages.ORDER_FAILED.format(error=str(e)), "SQUAREOFF_FAILED"
            )

    def square_off_option_position(
        self,
        position: Dict,
        quantity: Optional[int] = None,
        order_type: str = "market",
        limit_price: float = 0.0,
    ) -> Dict:
        """Square off one option position entry from get_positions()."""
        def _safe_str(value: Any, default: str = "") -> str:
            if value is None:
                return default
            return str(value).strip()

        def _safe_int(value: Any, default: int = 0) -> int:
            if value is None:
                return default
            try:
                if isinstance(value, str):
                    value = value.replace(",", "").strip()
                return int(float(value))
            except (ValueError, TypeError):
                return default

        stock_code = _safe_str(position.get("stock_code", ""))
        exchange_code = _safe_str(position.get("exchange_code", ""))
        expiry_date = _safe_str(position.get("expiry_date", ""))
        strike_price = str(_safe_int(position.get("strike_price", 0)))
        right_raw = _safe_str(position.get("right", position.get("option_type", "")))
        right = "call" if C.normalize_option_type(right_raw) == "CE" else "put"

        full_qty = _safe_int(position.get("quantity", 0))
        sq_qty = quantity if quantity and 0 < quantity <= abs(full_qty) else abs(full_qty)

        position_action = _safe_str(position.get("action", "")).lower()
        net_qty = _safe_int(position.get("quantity", 0))
        if position_action == "sell" or net_qty < 0:
            closing_action = "buy"
        else:
            closing_action = "sell"

        order_type = order_type.lower()
        price_str = str(limit_price) if order_type == "limit" and limit_price > 0 else ""

        return self.square_off(
            exchange_code=exchange_code,
            product="options",
            stock_code=stock_code,
            quantity=str(sq_qty),
            price=price_str,
            action=closing_action,
            order_type=order_type,
            expiry_date=expiry_date,
            right=right,
            strike_price=strike_price,
        )

    def cancel_order(self, order_id, exchange):
        self._require_connection()
        try:
            with self._api_lock:
                self.rate_limiter.wait()
                return self._ok(self.breeze.cancel_order(
                    exchange_code=exchange, order_id=order_id))
        except Exception as e:
            return self._err(C.ErrorMessages.CANCEL_FAILED.format(error=str(e)))

    def modify_order(self, order_id, exchange, quantity=0, price=0.0):
        self._require_connection()
        try:
            with self._api_lock:
                self.rate_limiter.wait()
                return self._ok(self.breeze.modify_order(
                    order_id=order_id,
                    exchange_code=exchange,
                    quantity=str(quantity) if quantity > 0 else "",
                    price=str(price) if price > 0 else "",
                    order_type=None, stoploss=None, validity=None
                ))
        except Exception as e:
            return self._err(C.ErrorMessages.MODIFY_FAILED.format(error=str(e)))

    def get_customer_details(self):
        self._require_connection()
        try:
            with self._api_lock:
                self.rate_limiter.wait()
                return self._ok(self.breeze.get_customer_details())
        except Exception as e:
            return self._err(str(e))

    # ─── Generic SDK bridge and extended API surface ───────────

    def call_sdk(self, method_name: str, *, retryable: bool = True, **kwargs):
        """
        Call any public method from BreezeConnect with consistent guardrails.

        This enables quick parity with new Breeze SDK methods while preserving:
        - connection checks
        - serialized API access
        - local rate limiter
        - normalized success/error envelope
        """
        self._require_connection()
        try:
            sdk_method = getattr(self.breeze, method_name)
        except AttributeError:
            return self._err(f"Breeze SDK method not found: {method_name}", "SDK_METHOD_NOT_FOUND")

        attempts = 3 if retryable else 1
        delay = 0.5
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                with self._api_lock:
                    self.rate_limiter.wait()
                    result = sdk_method(**kwargs)
                return self._ok(result)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not retryable or _is_permanent(exc) or attempt >= attempts:
                    break
                if _is_transient(exc):
                    time.sleep(delay)
                    delay *= 2
                    continue
                break

        return self._err(str(last_error) if last_error else "Unknown SDK error", "SDK_CALL_FAILED")

    # ---- Market data wrappers ----

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_quotes(self, stock_code: str, exchange_code: str, product_type: str,
                   right: str = "", strike_price: str = "", expiry_date: str = ""):
        expiry_iso = convert_to_breeze_datetime(expiry_date) if expiry_date else ""
        resp = self.call_sdk(
            "get_quotes",
            retryable=True,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product_type=product_type,
            right=right,
            strike_price=str(strike_price) if strike_price != "" else "",
            expiry_date=expiry_iso,
        )
        ok, msg = APIResponseValidator.validate_quote_response(resp, expected_symbol=stock_code)
        if not ok:
            log.debug("get_quotes validation notice for %s: %s", stock_code, msg)
        return resp

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_historical_data_v2(self, interval: str, from_date: str, to_date: str,
                               stock_code: str, exchange_code: str, product_type: str,
                               expiry_date: str = "", right: str = "", strike_price: str = ""):
        return self.call_sdk(
            "get_historical_data_v2",
            retryable=True,
            interval=interval,
            from_date=convert_to_breeze_iso_datetime(from_date),
            to_date=convert_to_breeze_iso_datetime(to_date, end_of_day=True),
            stock_code=stock_code,
            exchange_code=exchange_code,
            product_type=product_type,
            expiry_date=convert_to_breeze_datetime(expiry_date) if expiry_date else "",
            right=right,
            strike_price=str(strike_price) if strike_price != "" else "",
        )

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_option_chain_quotes(self, stock_code: str, exchange_code: str, expiry_date: str,
                                right: str, strike_price: str = ""):
        return self.call_sdk(
            "get_option_chain_quotes",
            retryable=True,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product_type="options",
            expiry_date=convert_to_breeze_datetime(expiry_date),
            right=right,
            strike_price=str(strike_price) if strike_price != "" else "",
        )

    # ---- Portfolio and order wrappers ----

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_portfolio_holdings(self, exchange_code: str = ""):
        return self.call_sdk("get_portfolio_holdings", retryable=True, exchange_code=exchange_code)

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_order_detail(self, exchange_code: str, order_id: str):
        return self.call_sdk("get_order_detail", retryable=True, exchange_code=exchange_code, order_id=order_id)

    @retry_api_call(max_attempts=3, initial_delay=0.5)
    def get_demat_holdings(self):
        return self.call_sdk("get_demat_holdings", retryable=True)

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_names(self, stock_code: str):
        return self.call_sdk("get_names", retryable=True, stock_code=stock_code)

    def set_funds(
        self,
        transaction_type: str,
        amount: str,
        segment: str,
    ) -> Dict:
        """Transfer funds between segments or initiate deposit/withdrawal."""
        self._require_connection()
        log.info(f"SET FUNDS: {transaction_type} ₹{amount} segment={segment}")
        return self.call_sdk(
            "set_funds",
            retryable=False,
            transaction_type=transaction_type,
            amount=str(amount),
            segment=segment,
        )

    def add_margin(
        self,
        product_type: str,
        stock_code: str,
        exchange_code: str,
        settlement_id: str = "",
        add_amount: str = "",
        margin_from_segment: str = "",
        margin_to_segment: str = "",
    ) -> Dict:
        """Add margin for an existing position."""
        self._require_connection()
        return self.call_sdk(
            "add_margin",
            retryable=False,
            product_type=product_type,
            stock_code=stock_code,
            exchange_code=exchange_code,
            settlement_id=settlement_id,
            add_amount=str(add_amount),
            margin_from_segment=margin_from_segment,
            margin_to_segment=margin_to_segment,
        )

    # ---- Funds and limits wrappers ----

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_margin_calculator(self, exchange_code: str, product_type: str, stock_code: str,
                              expiry_date: str, right: str, strike_price: str, action: str,
                              order_type: str, quantity: str, price: str = ""):
        return self.call_sdk(
            "get_margin_calculator",
            retryable=True,
            exchange_code=exchange_code,
            product_type=product_type,
            stock_code=stock_code,
            expiry_date=convert_to_breeze_datetime(expiry_date) if expiry_date else "",
            right=right,
            strike_price=str(strike_price),
            action=action,
            order_type=order_type,
            quantity=str(quantity),
            price=str(price) if price else "",
        )



    def preview_order(
        self,
        stock_code: str,
        exchange_code: str,
        product: str,
        order_type: str,
        price: str,
        action: str,
        quantity: str,
        special_flag: str = "N",
        stoploss: str = "",
        order_rate_fresh: str = "",
        expiry_date: str = "",
        right: str = "",
        strike_price: str = "",
    ) -> Dict:
        """Preview order charges before placement."""
        self._require_connection()
        if expiry_date:
            expiry_date = convert_to_breeze_datetime(expiry_date)

        return self.call_sdk(
            "preview_order",
            retryable=True,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product=product,
            order_type=order_type.lower(),
            price=price,
            action=action.lower(),
            quantity=str(quantity),
            special_flag=special_flag,
            stoploss=stoploss,
            order_rate_fresh=order_rate_fresh,
            expiry_date=expiry_date,
            right=right.lower() if right else "",
            strike_price=str(strike_price) if strike_price else "",
        )

    def limit_calculator(
        self,
        strike_price: str,
        product_type: str,
        expiry_date: str,
        underlying: str,
        exchange_code: str,
        order_flow: str,
        stop_loss_trigger: str,
        option_type: str,
        source_flag: str = "P",
        limit_rate: str = "",
        order_reference: str = "",
        available_quantity: str = "",
        market_type: str = "limit",
        fresh_order_limit: str = "",
    ) -> Dict:
        """Calculate valid limit price for OptionPlus orders."""
        self._require_connection()
        return self.call_sdk(
            "limit_calculator",
            retryable=True,
            strike_price=str(strike_price),
            product_type=product_type,
            expiry_date=convert_to_breeze_datetime(expiry_date) if expiry_date else "",
            underlying=underlying,
            exchange_code=exchange_code,
            order_flow=order_flow,
            stop_loss_trigger=str(stop_loss_trigger),
            option_type=option_type,
            source_flag=source_flag,
            limit_rate=str(limit_rate),
            order_reference=order_reference,
            available_quantity=str(available_quantity),
            market_type=market_type,
            fresh_order_limit=str(fresh_order_limit),
        )



    def get_futures_quote(
        self,
        stock_code: str,
        exchange_code: str,
        expiry_date: str,
    ) -> Dict:
        """Get real-time futures quote."""
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry_date) if expiry_date else ""
        return self.call_sdk(
            "get_quotes",
            retryable=True,
            stock_code=stock_code,
            exchange_code=exchange_code,
            expiry_date=expiry_iso,
            product_type="futures",
            right="",
            strike_price="",
        )

    def place_futures_order(
        self,
        stock_code: str,
        exchange_code: str,
        expiry: str,
        action: str,
        quantity: int,
        order_type: str,
        price: float = 0.0,
        stoploss: float = 0.0,
    ) -> Dict:
        """Place futures order via Breeze place_order endpoint."""
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry) if expiry else ""
        order_type = order_type.lower()
        if order_type == "market":
            price_str = ""
            stoploss_str = "0"
            sdk_order_type = "market"
        elif order_type == "limit":
            price_str = str(price)
            stoploss_str = "0"
            sdk_order_type = "limit"
        else:
            sdk_order_type = "stoploss"
            price_str = str(price) if price > 0 else ""
            stoploss_str = str(stoploss) if stoploss > 0 else "0"

        return self.call_sdk(
            "place_order",
            retryable=False,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product="futures",
            action=action.lower(),
            order_type=sdk_order_type,
            stoploss=stoploss_str,
            quantity=str(quantity),
            price=price_str,
            validity="day",
            disclosed_quantity="0",
            expiry_date=expiry_iso,
            right="",
            strike_price="",
            user_remark="Futures",
        )

    def place_amo_order(
        self,
        stock_code: str,
        exchange_code: str,
        product: str,
        action: str,
        quantity: str,
        order_type: str,
        price: str = "",
        expiry_date: str = "",
        right: str = "",
        strike_price: str = "",
    ) -> Dict:
        """
        Place an After-Market Order (AMO).

        Identical to place_order but with special_flag="Y".
        This method must NOT be retried.
        """
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry_date) if expiry_date else ""
        return self.call_sdk(
            "place_order",
            retryable=False,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product=product,
            action=action,
            quantity=str(quantity),
            order_type=order_type,
            price=str(price) if price else "",
            stoploss="0",
            validity="day",
            disclosed_quantity="0",
            expiry_date=expiry_iso,
            right=right,
            strike_price=str(strike_price) if strike_price else "",
            special_flag="Y",
            user_remark="AMO",
        )

    def place_option_plus_order(
        self,
        stock_code: str,
        exchange_code: str,
        action: str,
        quantity: str,
        price: str,
        expiry_date: str,
        right: str,
        strike_price: str,
        stoploss: str,
        order_type: str = "limit",
    ) -> Dict:
        """
        Place an OptionPlus cover order.

        stoploss is mandatory for OptionPlus and validated before placement.
        """
        self._require_connection()
        if not str(stoploss or "").strip():
            return self._err("OptionPlus requires a non-empty stoploss.", "VALIDATION_ERROR")

        expiry_iso = convert_to_breeze_datetime(expiry_date) if expiry_date else ""
        return self.call_sdk(
            "place_order",
            retryable=False,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product="optionplus",
            action=action,
            quantity=str(quantity),
            order_type=order_type,
            price=str(price),
            stoploss=str(stoploss),
            validity="day",
            disclosed_quantity="0",
            expiry_date=expiry_iso,
            right=right,
            strike_price=str(strike_price),
            user_remark="OptionPlus",
        )

    # ---- Trading utility wrappers ----

    def place_order_raw(self, **kwargs):
        """Raw pass-through order API for advanced UI flows (non-retry by design)."""
        return self.call_sdk("place_order", retryable=False, **kwargs)

    def cancel_order_raw(self, **kwargs):
        """Raw pass-through cancel API (non-retry by design)."""
        return self.call_sdk("cancel_order", retryable=False, **kwargs)

    def modify_order_raw(self, **kwargs):
        """Raw pass-through modify API (non-retry by design)."""
        return self.call_sdk("modify_order", retryable=False, **kwargs)

    # ---- WebSocket wrappers ----

    def ws_connect(self):
        """Open Breeze websocket connection."""
        return self.call_sdk("ws_connect", retryable=False)

    def ws_disconnect(self):
        """Close Breeze websocket connection."""
        return self.call_sdk("ws_disconnect", retryable=False)


    def subscribe_feeds(self, **kwargs):
        """Subscribe feeds using Breeze SDK-compatible kwargs."""
        return self.call_sdk("subscribe_feeds", retryable=False, **kwargs)

    def unsubscribe_feeds(self, **kwargs):
        """Unsubscribe feeds using Breeze SDK-compatible kwargs."""
        return self.call_sdk("unsubscribe_feeds", retryable=False, **kwargs)

    # ---- Discoverability ----

    def list_available_sdk_methods(self) -> List[str]:
        """List callable public methods exposed by installed Breeze SDK client."""
        self._require_connection()
        methods: List[str] = []
        for name in dir(self.breeze):
            if name.startswith("_"):
                continue
            attr = getattr(self.breeze, name)
            if callable(attr):
                methods.append(name)
        return sorted(methods)


class OrderSlicer:
    """Execute a large order in smaller slices."""

    def __init__(
        self,
        client: "BreezeAPIClient",
        n_slices: int = 3,
        interval_seconds: float = 1.0,
        jitter_pct: float = 0.2,
    ):
        self._client = client
        self._n = max(1, int(n_slices))
        self._interval = max(0.0, float(interval_seconds))
        self._jitter = max(0.0, float(jitter_pct))

    def execute(self, place_order_kwargs: Dict, total_quantity: int) -> Dict:
        """Execute an order in slices and stop on first failure."""
        total_qty = int(total_quantity)
        if total_qty <= 0:
            return {
                "success": False,
                "slices_placed": 0,
                "slices_failed": 0,
                "total_quantity_placed": 0,
                "order_ids": [],
                "responses": [],
            }

        base_qty = total_qty // self._n
        remainder = total_qty % self._n
        quantities = [base_qty] * self._n
        quantities[0] += remainder

        order_ids: List[str] = []
        responses: List[Dict] = []
        slices_placed = 0
        slices_failed = 0
        total_quantity_placed = 0

        for i, qty in enumerate(quantities):
            if qty <= 0:
                continue
            kwargs = dict(place_order_kwargs)
            kwargs["quantity"] = str(qty)
            resp = self._client.place_order_raw(**kwargs)
            responses.append(resp)

            if resp.get("success"):
                slices_placed += 1
                total_quantity_placed += qty
                success_data = (resp.get("data", {}) or {}).get("Success")
                if isinstance(success_data, list) and success_data:
                    order_ids.append(str(success_data[0].get("order_id", "")))
            else:
                slices_failed += 1
                log.warning(f"Slice {i + 1}/{self._n} failed: {resp.get('message')}")
                break

            if i < self._n - 1:
                jitter = self._interval * self._jitter * (random.random() * 2 - 1)
                time.sleep(max(0.1, self._interval + jitter))

        return {
            "success": slices_placed > 0,
            "slices_placed": slices_placed,
            "slices_failed": slices_failed,
            "total_quantity_placed": total_quantity_placed,
            "order_ids": order_ids,
            "responses": responses,
        }
