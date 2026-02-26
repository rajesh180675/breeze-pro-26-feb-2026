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
import time
import hashlib
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from functools import wraps

from breeze_connect import BreezeConnect
import app_config as C

log = logging.getLogger(__name__)


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

    @retry_api_call(max_attempts=2, initial_delay=1.0)
    def connect(self, session_token: str):
        self.breeze = BreezeConnect(api_key=self.api_key)
        self.breeze.generate_session(api_secret=self.api_secret, session_token=session_token)
        self.connected = True
        self._connection_time = time.time()
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
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_portfolio_positions())

    @retry_api_call(max_attempts=3, initial_delay=1.0, backoff=1.5)
    def get_option_chain(self, stock_code: str, exchange: str, expiry: str):
        """
        Fetch full option chain for a given instrument and expiry.

        Breeze Connect requires:
          - exchange_code: "NFO" for NSE derivatives, "BFO" for BSE derivatives
          - product_type: "options"
          - expiry_date: ISO-8601 format "YYYY-MM-DDTHH:MM:SS.000Z"
          - right: "" to get both calls and puts
          - strike_price: "" to get all strikes
        """
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry)
        log.info(f"get_option_chain: stock={stock_code} exchange={exchange} expiry_iso={expiry_iso}")
        with self._api_lock:
            self.rate_limiter.wait()
            data = self.breeze.get_option_chain_quotes(
                stock_code=stock_code,
                exchange_code=exchange,
                product_type="options",
                expiry_date=expiry_iso,
                right="",
                strike_price=""
            )
        log.info(f"get_option_chain raw response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return self._ok(data)

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_quotes(self, stock_code: str, exchange: str, expiry: str,
                   strike: int, option_type: str):
        """
        Fetch LTP and market data for a specific option contract.
        expiry_date passed as ISO-8601 as required by Breeze API.
        """
        self._require_connection()
        expiry_iso = convert_to_breeze_datetime(expiry)
        right = "call" if option_type.upper() == "CE" else "put"
        log.info(f"get_quotes: {stock_code} {exchange} {expiry_iso} {strike} {right}")
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
    def get_order_list(self, exchange="", from_date="", to_date=""):
        self._require_connection()
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_order_list(
                exchange_code=exchange,
                from_date=convert_to_breeze_iso_datetime(from_date),
                to_date=convert_to_breeze_iso_datetime(to_date, end_of_day=True)
            ))

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_trade_list(self, exchange="", from_date="", to_date=""):
        self._require_connection()
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_trade_list(
                exchange_code=exchange,
                from_date=convert_to_breeze_iso_datetime(from_date),
                to_date=convert_to_breeze_iso_datetime(to_date, end_of_day=True)
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
            price_str = str(price) if order_type.lower() == "limit" and price > 0 else "0"
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
            log.info(f"place_order response: {resp}")
            return self._ok(resp)
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

    def square_off(self, stock_code, exchange, expiry, strike, option_type,
                   quantity, position_type, order_type="market", price=0.0):
        action = "buy" if position_type == "short" else "sell"
        return self.place_order(stock_code, exchange, expiry, strike, option_type,
                                action, quantity, order_type, price)

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
