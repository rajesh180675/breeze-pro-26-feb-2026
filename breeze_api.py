"""
Breeze API Client v8.0

Critical fixes from v7.0:
1. Retry decorator ACTUALLY retries (exceptions propagate, not caught inside methods)
2. Order idempotency prevents duplicate submissions
3. Orders are NOT auto-retried (prevents double orders)
4. get_spot_price() for accurate Greeks
5. Thread-safe with API lock for background risk monitor
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
# FIXED RETRY DECORATOR
# ═══════════════════════════════════════════════════════════════

def retry_api_call(max_attempts: int = 3, initial_delay: float = 0.5, backoff: float = 2.0):
    """
    Retry decorator that works correctly.

    Methods must RAISE exceptions (not catch them internally).
    This decorator catches, classifies, retries transient errors,
    and converts final failure into an error dict.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    # Check for transient error in response body
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
        """Returns True if order should proceed (new key)."""
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
# DATE CONVERSION
# ═══════════════════════════════════════════════════════════════

def convert_to_breeze_date(date_str: str) -> str:
    if not date_str or not date_str.strip():
        return ""
    date_str = date_str.strip()
    formats = [
        ("%d-%b-%Y", False), ("%d-%B-%Y", True), ("%Y-%m-%d", True),
        ("%Y-%m-%dT%H:%M:%S", True), ("%Y-%m-%dT%H:%M:%S.%f", True),
        ("%d/%m/%Y", True), ("%d-%m-%Y", True),
    ]
    for fmt, needs_conv in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%d-%b-%Y") if needs_conv else date_str
        except ValueError:
            continue
    log.warning(f"Could not parse date: {date_str}")
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

    def _ok(self, data):
        return {"success": True, "data": data, "message": "", "error_code": None}

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
        self._require_connection()
        expiry_date = convert_to_breeze_date(expiry)
        log.info(f"Fetching chain: {stock_code} {exchange} {expiry_date}")
        with self._api_lock:
            self.rate_limiter.wait()
            data = self.breeze.get_option_chain_quotes(
                stock_code=stock_code, exchange_code=exchange, product_type="options",
                expiry_date=expiry_date, right="", strike_price=""
            )
        return self._ok(data)

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_quotes(self, stock_code: str, exchange: str, expiry: str,
                   strike: int, option_type: str):
        self._require_connection()
        with self._api_lock:
            self.rate_limiter.wait()
            data = self.breeze.get_quotes(
                stock_code=stock_code, exchange_code=exchange,
                expiry_date=convert_to_breeze_date(expiry), product_type="options",
                right="call" if option_type.upper() == "CE" else "put",
                strike_price=str(strike)
            )
        return self._ok(data)

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_spot_price(self, stock_code: str, exchange: str):
        """Fetch underlying index spot price."""
        self._require_connection()
        cfg = None
        for name, c in C.INSTRUMENTS.items():
            if c.api_code == stock_code:
                cfg = c
                break
        spot_code = cfg.spot_code if cfg and cfg.spot_code else stock_code
        spot_exchange = cfg.spot_exchange if cfg and cfg.spot_exchange else (
            "NSE" if exchange == "NFO" else "BSE"
        )
        with self._api_lock:
            self.rate_limiter.wait()
            data = self.breeze.get_quotes(
                stock_code=spot_code, exchange_code=spot_exchange,
                product_type="cash", expiry_date="", right="", strike_price=""
            )
        return self._ok(data)

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_order_list(self, exchange="", from_date="", to_date=""):
        self._require_connection()
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_order_list(
                exchange_code=exchange, from_date=from_date, to_date=to_date))

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_trade_list(self, exchange="", from_date="", to_date=""):
        self._require_connection()
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_trade_list(
                exchange_code=exchange, from_date=from_date, to_date=to_date))

    @retry_api_call(max_attempts=2, initial_delay=0.5)
    def get_margin(self, stock_code, exchange, expiry, strike, option_type, action, quantity):
        self._require_connection()
        with self._api_lock:
            self.rate_limiter.wait()
            return self._ok(self.breeze.get_margin(
                exchange_code=exchange, stock_code=stock_code, product_type="options",
                right="call" if option_type.upper() == "CE" else "put",
                strike_price=str(strike), expiry_date=convert_to_breeze_date(expiry),
                quantity=str(quantity), action=action.lower(), order_type="market", price=""
            ))

    # ─── Order placement (NOT retried, idempotency protected) ─

    def place_order(self, stock_code, exchange, expiry, strike, option_type,
                    action, quantity, order_type="market", price=0.0):
        self._require_connection()
        idem_key = self.idempotency.make_key(stock_code, strike, option_type, action, quantity)
        if not self.idempotency.check_and_reserve(idem_key):
            return self._err(
                "Duplicate order detected. Same order was placed within the last 60 seconds.",
                "DUPLICATE_ORDER"
            )
        try:
            right = "call" if option_type.upper() == "CE" else "put"
            log.info(f"ORDER: {action.upper()} {stock_code} {strike} {option_type} x{quantity}")
            with self._api_lock:
                self.rate_limiter.wait()
                resp = self.breeze.place_order(
                    stock_code=stock_code, exchange_code=exchange, product="options",
                    action=action.lower(), order_type=order_type.lower(),
                    quantity=str(quantity),
                    price=str(price) if order_type.lower() == "limit" else "",
                    validity="day", validity_date="", disclosed_quantity="", stoploss="",
                    expiry_date=convert_to_breeze_date(expiry), right=right,
                    strike_price=str(strike)
                )
            return self._ok(resp)
        except Exception as e:
            self.idempotency.release(idem_key)
            log.error(f"Order failed: {e}")
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
                return self._ok(self.breeze.cancel_order(exchange_code=exchange, order_id=order_id))
        except Exception as e:
            return self._err(C.ErrorMessages.CANCEL_FAILED.format(error=str(e)))

    def modify_order(self, order_id, exchange, quantity=0, price=0.0):
        self._require_connection()
        try:
            with self._api_lock:
                self.rate_limiter.wait()
                return self._ok(self.breeze.modify_order(
                    order_id=order_id, exchange_code=exchange,
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
