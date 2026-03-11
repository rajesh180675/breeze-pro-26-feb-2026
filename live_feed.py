"""Live feed engine for Breeze PRO."""

from __future__ import annotations

import csv
import logging
import queue
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from breeze_connect import BreezeConnect

import app_config as C

log = logging.getLogger(__name__)

EXCHANGE_DIGIT = {"NSE": "1", "NFO": "4", "BSE": "6", "BSE_FO": "13", "BFO": "14"}
DEPTH_L1 = "1"
DEPTH_L2 = "4"

SECURITY_MASTER_CSV_URLS = {
    "NSE_CM": "https://api.icicidirect.com/breezeapi/documents/NSE_BSE_Instruments.csv",
    "NSE_FO": "https://api.icicidirect.com/breezeapi/documents/NSE_BSE_Instruments.csv",
    "BSE_CM": "https://api.icicidirect.com/breezeapi/documents/NSE_BSE_Instruments.csv",
    "BFO": "https://api.icicidirect.com/breezeapi/documents/BSE_Derivatives.csv",
}
SECURITY_MASTER_DIR = Path("data/security_master")
SECURITY_MASTER_TTL_HOURS = 24
MAX_SUBSCRIPTIONS = 500
MAX_TICK_HISTORY = 10_000
MAX_BAR_HISTORY = 1_000
WORKER_QUEUE_MAXSIZE = 50_000
HEALTH_STALE_SECONDS = 60


class TokenResolutionError(Exception): ...


class LiveFeedNotConnectedError(Exception): ...


@dataclass
class SecurityRecord:
    token: str
    short_name: str
    series: str
    exchange_code: str
    company_name: str
    expiry_date: str
    strike_price: float
    option_type: str
    lot_size: int
    tick_size: float
    isin: str

    @property
    def instrument_key(self) -> str:
        parts = [self.exchange_code, self.short_name]
        if self.expiry_date:
            parts.append(self.expiry_date[:10])
        if self.strike_price:
            parts.append(str(int(self.strike_price)))
        if self.option_type:
            parts.append(self.option_type.lower())
        return "|".join(parts)


@dataclass
class TickData:
    stock_token: str
    symbol: str
    exchange: str
    product_type: str
    expiry: str
    strike: float
    right: str
    ltp: float
    ltt: str
    ltq: int
    volume: int
    open_interest: int
    oi_change: int
    best_bid: float
    best_bid_qty: int
    best_ask: float
    best_ask_qty: int
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    change_pct: float
    upper_circuit: float
    lower_circuit: float
    week_52_high: float
    week_52_low: float
    total_buy_qty: int
    total_sell_qty: int
    market_depth: List[Dict]
    received_at: float


@dataclass
class OHLCVBar:
    stock_token: str
    interval: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int
    received_at: float


class OrderEventType:
    PLACED = "ORDER_PLACED"
    MODIFIED = "ORDER_MODIFIED"
    CANCELLED = "ORDER_CANCELLED"
    FILLED = "ORDER_FILLED"
    PARTIAL = "ORDER_PARTIAL_FILL"
    REJECTED = "ORDER_REJECTED"
    EXPIRED = "ORDER_EXPIRED"


@dataclass
class OrderEvent:
    event_type: str
    order_id: str
    exchange_order_id: str
    stock_code: str
    exchange_code: str
    product: str
    action: str
    order_type: str
    quantity: int
    filled_quantity: int
    remaining_quantity: int
    price: float
    average_fill_price: float
    status: str
    rejection_reason: str
    timestamp: str
    received_at: float


class SecurityMasterCache:
    COLUMN_ALIASES: Dict[str, List[str]] = {
        "token": ["Token", "token", "ISIN_CODE", "Code"],
        "short_name": ["ShortName", "Scrip_Name", "SYMBOL", "Symbol", "Short_Name"],
        "series": ["Series", "series", "SERIES"],
        "company_name": ["CompanyName", "Company_Name", "COMPANY_NAME", "Name"],
        "exchange_code": ["ExchangeCode", "Exchange", "EXCHANGE"],
        "expiry_date": ["ExpiryDate", "Expiry_Date", "EXPIRY_DATE", "Expiry"],
        "strike_price": ["StrikePrice", "Strike_Price", "STRIKE_PRICE", "Strike"],
        "option_type": ["OptionType", "Option_Type", "OPTION_TYPE", "Right"],
        "lot_size": ["LotSize", "Lot_Size", "LOT_SIZE", "Lot"],
        "tick_size": ["TickSize", "Tick_Size", "TICK_SIZE"],
        "isin": ["ISIN", "Isin", "isin"],
    }

    def __init__(self, data_dir: str = str(SECURITY_MASTER_DIR)):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._by_token: Dict[str, SecurityRecord] = {}
        self._by_key: Dict[str, SecurityRecord] = {}
        self._by_name: Dict[str, Dict[str, List[SecurityRecord]]] = {}
        self._loaded = False
        self._lock = threading.Lock()

    def load(self, force_refresh: bool = False) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for exchange_name, url in SECURITY_MASTER_CSV_URLS.items():
                path = self._get_local_path(exchange_name)
                if force_refresh or not self._is_fresh(path):
                    self._download(url, path, exchange_name)
                counts[exchange_name] = self._parse_and_index(path, exchange_name)
            self._loaded = True
            return counts

    def find_options(self, exchange_code: str, short_name: str, expiry_date: str = "", strike: float = 0.0,
                     option_type: str = "") -> List[SecurityRecord]:
        candidates = self._by_name.get(exchange_code, {}).get(short_name, [])
        out: List[SecurityRecord] = []
        for rec in candidates:
            if expiry_date and not rec.expiry_date.startswith(expiry_date):
                continue
            if strike and abs(rec.strike_price - strike) > 0.01:
                continue
            if option_type and rec.option_type.lower() != option_type.lower():
                continue
            out.append(rec)
        return out

    def is_loaded(self) -> bool:
        return self._loaded

    def _get_local_path(self, exchange_name: str) -> Path:
        return self._dir / f"{datetime.now().strftime('%Y%m%d')}_{exchange_name}.csv"

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists() or path.stat().st_size < 100:
            return False
        return ((time.time() - path.stat().st_mtime) / 3600) < SECURITY_MASTER_TTL_HOURS

    def _download(self, url: str, path: Path, exchange_name: str) -> None:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        except Exception as exc:
            log.warning(f"Security master download failed for {exchange_name}: {exc}")
            existing = sorted(self._dir.glob(f"*_{exchange_name}.csv"), reverse=True)
            if existing and existing[0] != path:
                import shutil
                shutil.copy(existing[0], path)

    def _parse_and_index(self, path: Path, exchange_name: str) -> int:
        if not path.exists():
            return 0
        count = 0
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            col_map = self._build_col_map(headers)
            for row in reader:
                rec = self._parse_row(row, col_map, exchange_name)
                if rec and rec.token:
                    self._by_token[rec.token] = rec
                    self._by_key[rec.instrument_key] = rec
                    self._by_name.setdefault(rec.exchange_code, {}).setdefault(rec.short_name, []).append(rec)
                    count += 1
        return count

    def _build_col_map(self, headers: List[str]) -> Dict[str, str]:
        out = {}
        for canonical, aliases in self.COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in headers:
                    out[canonical] = alias
                    break
        return out

    def _parse_row(self, row: Dict, col_map: Dict[str, str], exchange_name: str) -> Optional[SecurityRecord]:
        def get(field: str, default: str = "") -> str:
            col = col_map.get(field)
            return row.get(col, default).strip() if col else default

        token = get("token")
        if not token:
            return None
        strike = float((get("strike_price", "0") or "0").replace(",", "") or 0)
        lot = int(float(get("lot_size", "1") or 1))
        tick = float(get("tick_size", "0.05") or 0.05)
        exchange_code = get("exchange_code") or self._infer_exchange(exchange_name)
        return SecurityRecord(
            token=token,
            short_name=get("short_name"),
            series=get("series"),
            exchange_code=exchange_code,
            company_name=get("company_name"),
            expiry_date=self._parse_expiry(get("expiry_date")),
            strike_price=strike,
            option_type=get("option_type"),
            lot_size=lot,
            tick_size=tick,
            isin=get("isin"),
        )

    @staticmethod
    def _parse_expiry(raw: str) -> str:
        if not raw:
            return ""
        for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%Y%m%d"]:
            try:
                return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return raw.strip()

    @staticmethod
    def _infer_exchange(exchange_name: str) -> str:
        return {"NSE_CM": "NSE", "NSE_FO": "NFO", "BSE_CM": "BSE", "BFO": "BFO"}.get(exchange_name, exchange_name)


class StockTokenResolver:
    def __init__(self, security_master: SecurityMasterCache, breeze: BreezeConnect, depth: str = DEPTH_L1):
        self._sm = security_master
        self._breeze = breeze
        self._depth = depth
        self._cache: Dict[str, str] = {}
        self._lock = threading.Lock()

    def resolve(self, exchange: str, stock_code: str, product_type: str = "cash", expiry: str = "", strike: float = 0.0,
                right: str = "") -> str:
        key = self._make_key(exchange, stock_code, product_type, expiry, strike, right)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        records = self._sm.find_options(
            exchange_code=exchange,
            short_name=stock_code,
            expiry_date=expiry,
            strike=strike,
            option_type="Call" if right.lower() == "call" else ("Put" if right.lower() == "put" else ""),
        )
        if records:
            token_str = self._build_token_string(exchange, records[0].token)
            with self._lock:
                self._cache[key] = token_str
            return token_str

        api_resp = self._breeze.get_names(exchange_code=exchange, stock_code=stock_code)
        token = self._extract_token_from_names_response(api_resp, strike, right, expiry)
        if token:
            token_str = self._build_token_string(exchange, token)
            with self._lock:
                self._cache[key] = token_str
            return token_str
        raise TokenResolutionError(f"Cannot resolve token for {exchange}:{stock_code}")

    def resolve_batch(self, instruments: List[Dict], max_workers: int = 8) -> Dict[str, str]:
        results: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_inst = {
                pool.submit(
                    self.resolve,
                    inst["exchange"],
                    inst["stock_code"],
                    inst.get("product_type", "cash"),
                    inst.get("expiry", ""),
                    inst.get("strike", 0.0),
                    inst.get("right", ""),
                ): inst
                for inst in instruments
            }
            for future in as_completed(future_to_inst):
                inst = future_to_inst[future]
                key = self._make_key(inst["exchange"], inst["stock_code"], inst.get("product_type", "cash"),
                                     inst.get("expiry", ""), inst.get("strike", 0.0), inst.get("right", ""))
                try:
                    results[key] = future.result()
                except TokenResolutionError as exc:
                    log.warning(f"Batch resolve failed: {exc}")
        return results

    @staticmethod
    def _make_key(exchange, stock_code, product_type, expiry, strike, right) -> str:
        return f"{exchange}|{stock_code}|{product_type}|{expiry}|{strike}|{right}"

    def _build_token_string(self, exchange: str, token: str) -> str:
        return f"{EXCHANGE_DIGIT.get(exchange, '1')}.{self._depth}!{token}"

    @staticmethod
    def _extract_token_from_names_response(api_resp: Dict, strike: float, right: str, expiry: str) -> Optional[str]:
        success = api_resp.get("Success") if isinstance(api_resp, dict) else None
        if not isinstance(success, list) or not success:
            return None
        for item in success:
            if not isinstance(item, dict):
                continue
            if not strike and not right:
                return str(item.get("Token", ""))
            item_strike = float(item.get("StrikePrice", "0") or "0")
            item_right = str(item.get("Right", "") or "").lower()
            item_expiry = str(item.get("ExpiryDate", "") or "")
            if abs(item_strike - strike) < 0.01 and item_right.startswith(right[:3].lower()) and (not expiry or expiry in item_expiry):
                return str(item.get("Token", ""))
        return None


class TickStore:
    def __init__(self, max_history_per_token: int = MAX_TICK_HISTORY):
        self._latest: Dict[str, TickData] = {}
        self._history: Dict[str, deque] = {}
        self._max_history = max_history_per_token
        self._lock = threading.RLock()
        self._total_ticks = 0

    def put(self, tick: TickData) -> None:
        with self._lock:
            self._latest[tick.stock_token] = tick
            if tick.stock_token not in self._history:
                self._history[tick.stock_token] = deque(maxlen=self._max_history)
            self._history[tick.stock_token].append(tick)
            self._total_ticks += 1

    def get_latest(self, stock_token: str) -> Optional[TickData]:
        return self._latest.get(stock_token)

    def get_latest_ltp(self, stock_token: str) -> Optional[float]:
        tick = self._latest.get(stock_token)
        return tick.ltp if tick else None

    def get_all_latest(self) -> Dict[str, "TickData"]:
        """Return a snapshot of the latest tick for every subscribed token."""
        with self._lock:
            return dict(self._latest)

    def get_history(self, stock_token: str) -> List["TickData"]:
        """Return tick history for a token (oldest first)."""
        with self._lock:
            buf = self._history.get(stock_token)
            return list(buf) if buf else []

    def clear_tokens(self, tokens: List[str]) -> None:
        with self._lock:
            for token in tokens:
                self._latest.pop(token, None)
                self._history.pop(token, None)

    @property
    def total_ticks(self) -> int:
        return self._total_ticks


class BarStore:
    VALID_INTERVALS = frozenset({"1second", "1minute", "5minute", "30minute", "1day"})

    def __init__(self, max_bars: int = MAX_BAR_HISTORY):
        self._bars: Dict[Tuple[str, str], deque] = {}
        self._max_bars = max_bars
        self._lock = threading.RLock()

    def put(self, bar: OHLCVBar) -> None:
        key = (bar.stock_token, bar.interval)
        with self._lock:
            if key not in self._bars:
                self._bars[key] = deque(maxlen=self._max_bars)
            buf = self._bars[key]
            if buf and buf[-1].timestamp == bar.timestamp:
                prev = buf[-1]
                buf[-1] = OHLCVBar(bar.stock_token, bar.interval, bar.timestamp, prev.open, max(prev.high, bar.high),
                                   min(prev.low, bar.low), bar.close, bar.volume, bar.open_interest, bar.received_at)
            else:
                buf.append(bar)


class OrderNotificationBus:
    MAX_EVENT_HISTORY = 200

    def __init__(self):
        self._subscribers: Dict[str, Tuple[Callable[[OrderEvent], None], Optional[List[str]]]] = {}
        self._history: deque = deque(maxlen=self.MAX_EVENT_HISTORY)
        self._lock = threading.RLock()

    def subscribe(self, callback: Callable[[OrderEvent], None], event_types: Optional[List[str]] = None) -> str:
        sub_id = str(uuid.uuid4())
        with self._lock:
            self._subscribers[sub_id] = (callback, event_types)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            return bool(self._subscribers.pop(subscription_id, None))

    def publish(self, event: OrderEvent) -> None:
        with self._lock:
            self._history.append(event)
            subs = list(self._subscribers.values())
        for callback, event_types in subs:
            if event_types is None or event.event_type in event_types:
                callback(event)


class FeedState:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    STOPPED = "STOPPED"


class SubscriptionType:
    QUOTE = "quote"
    OHLCV = "ohlcv"
    ORDER_NOTIFY = "order_notify"


@dataclass
class SubscriptionRecord:
    stock_token: str
    sub_type: str
    interval: Optional[str]
    get_market_depth: bool
    subscribed_at: float


class LiveFeedManager:
    BACKOFF_SEQUENCE = [1, 2, 4, 8, 16, 30]

    def __init__(self, breeze: BreezeConnect, tick_store: TickStore, bar_store: BarStore, order_bus: OrderNotificationBus,
                 max_subscriptions: int = MAX_SUBSCRIPTIONS):
        self._breeze = breeze
        self._tick_store = tick_store
        self._bar_store = bar_store
        self._order_bus = order_bus
        self._max_subs = max_subscriptions
        self._state = FeedState.DISCONNECTED
        self._subscriptions: Dict[str, SubscriptionRecord] = {}
        self._tick_queue: queue.Queue = queue.Queue(maxsize=WORKER_QUEUE_MAXSIZE)
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._connect_count = 0
        self._reconnect_count = 0
        self._total_ticks = 0
        self._last_tick_time = 0.0
        self._errors: List[Dict] = []

    def connect(self) -> None:
        if self._state == FeedState.STOPPED:
            raise LiveFeedNotConnectedError("Feed manager has been stopped. Create a new instance.")
        self._stop_event.clear()
        self._state = FeedState.CONNECTING
        self._breeze.on_ticks = self._on_ticks_raw
        threading.Thread(target=self._worker_loop, daemon=True, name="LiveFeedWorker").start()
        threading.Thread(target=self._connect_with_backoff, daemon=True, name="LiveFeedConnector").start()

    def disconnect(self, clear_subscriptions: bool = True) -> None:
        self._stop_event.set()
        try:
            self._breeze.ws_disconnect()
        except Exception:
            pass
        if clear_subscriptions:
            with self._lock:
                stale_tokens = [k for k, v in self._subscriptions.items() if v.sub_type == SubscriptionType.QUOTE]
                self._subscriptions.clear()
            self._tick_store.clear_tokens(stale_tokens)
        self._state = FeedState.DISCONNECTED

    def is_connected(self) -> bool:
        return self._state == FeedState.CONNECTED

    def subscribe_quote(self, stock_token: str, get_market_depth: bool = False) -> bool:
        with self._lock:
            if stock_token in self._subscriptions:
                return True
            if len(self._subscriptions) >= self._max_subs:
                return False
            depth = DEPTH_L2 if get_market_depth else DEPTH_L1
            token = self._adjust_depth(stock_token, depth)
            self._breeze.subscribe_feeds(stock_token=token)
            self._subscriptions[stock_token] = SubscriptionRecord(stock_token, SubscriptionType.QUOTE, None,
                                                                  get_market_depth, time.time())
            return True

    def subscribe_ohlcv(self, stock_token: str, interval: str, exchange_code: str, stock_code: str, product_type: str,
                        expiry_date: str = "", strike_price: str = "", right: str = "") -> bool:
        with self._lock:
            key = f"ohlcv|{stock_token}|{interval}"
            if key in self._subscriptions:
                return True
            if len(self._subscriptions) >= self._max_subs:
                return False
            self._breeze.subscribe_feeds(exchange_code=exchange_code, stock_code=stock_code, product_type=product_type,
                                         expiry_date=expiry_date, strike_price=strike_price, right=right,
                                         interval=interval)
            self._subscriptions[key] = SubscriptionRecord(stock_token, SubscriptionType.OHLCV, interval, False,
                                                          time.time())
            return True

    def subscribe_order_notifications(self) -> bool:
        with self._lock:
            key = "ORDER_NOTIFY"
            if key in self._subscriptions:
                return True
            self._breeze.subscribe_feeds(get_order_notification=True)
            self._subscriptions[key] = SubscriptionRecord("", SubscriptionType.ORDER_NOTIFY, None, False, time.time())
            return True

    def unsubscribe_quote(self, stock_token: str) -> bool:
        with self._lock:
            record = self._subscriptions.get(stock_token)
            if record is None:
                return False
            try:
                depth = DEPTH_L2 if record.get_market_depth else DEPTH_L1
                token = self._adjust_depth(stock_token, depth)
                if hasattr(self._breeze, "unsubscribe_feeds"):
                    self._breeze.unsubscribe_feeds(stock_token=token)
            except Exception:
                pass
            self._subscriptions.pop(stock_token, None)
            return True

    def get_health_stats(self) -> Dict:
        """Return live-feed health statistics for monitoring / tests."""
        now = time.time()
        stale = (
            bool(self._last_tick_time)
            and (now - self._last_tick_time) > HEALTH_STALE_SECONDS
            and C.is_market_open()
        )
        last_secs_ago = (now - self._last_tick_time) if self._last_tick_time else None
        with self._lock:
            sub_count = len(self._subscriptions)
        return {
            "state": self._state,
            "total_subscriptions": sub_count,
            "total_ticks": self._total_ticks,
            "last_tick_time": self._last_tick_time,
            "last_tick_secs_ago": last_secs_ago,   # seconds since last tick, None if no ticks yet
            "connect_count": self._connect_count,
            "reconnect_count": self._reconnect_count,
            "is_stale": stale,
            "queue_size": self._tick_queue.qsize(),
        }

    def _restore_subscriptions(self) -> None:
        """Re-subscribe all previously registered tokens after a reconnect."""
        with self._lock:
            subs = dict(self._subscriptions)
        for key, rec in subs.items():
            try:
                if rec.sub_type == SubscriptionType.QUOTE:
                    depth = DEPTH_L2 if rec.get_market_depth else DEPTH_L1
                    token = self._adjust_depth(rec.stock_token, depth)
                    self._breeze.subscribe_feeds(stock_token=token)
                elif rec.sub_type == SubscriptionType.ORDER_NOTIFY:
                    self._breeze.subscribe_feeds(get_order_notification=True)
                # OHLCV subs cannot be fully restored without original params;
                # their metadata is stored in the SubscriptionRecord if available.
            except Exception as exc:  # pragma: no cover
                log.warning("_restore_subscriptions failed for %s: %s", key, exc)

    def _connect_with_backoff(self) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            backoff = self.BACKOFF_SEQUENCE[min(attempt, len(self.BACKOFF_SEQUENCE) - 1)]
            try:
                self._breeze.ws_connect()
                if self._connect_count > 0:
                    self._restore_subscriptions()
                self._last_tick_time = 0.0
                self._state = FeedState.CONNECTED
                self._connect_count += 1
                attempt = 0
                self._wait_for_disconnect()
            except Exception as exc:
                self._state = FeedState.RECONNECTING
                self._reconnect_count += 1
                self._errors.append({"time": datetime.now().isoformat(), "error": str(exc), "attempt": attempt})
                time.sleep(backoff)
                attempt += 1

    def _wait_for_disconnect(self) -> None:
        while not self._stop_event.is_set() and self.is_connected():
            if self._last_tick_time and (time.time() - self._last_tick_time) > HEALTH_STALE_SECONDS and C.is_market_open():
                log.warning("Feed stale")
                self._state = FeedState.RECONNECTING
                try:
                    self._breeze.ws_disconnect()
                except Exception:
                    pass
                return
            time.sleep(5)

    def _on_ticks_raw(self, raw_tick: dict) -> None:
        try:
            self._tick_queue.put_nowait(raw_tick)
        except queue.Full:
            log.warning("Tick queue full")

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                raw_tick = self._tick_queue.get(timeout=1.0)
                self._route_tick(raw_tick)
                self._total_ticks += 1
                self._last_tick_time = time.time()
            except queue.Empty:
                continue

    def _route_tick(self, raw_tick: dict) -> None:
        tick_type = self._classify_tick(raw_tick)
        if tick_type == SubscriptionType.QUOTE:
            tick = self._parse_quote_tick(raw_tick)
            if tick:
                self._tick_store.put(tick)
        elif tick_type == SubscriptionType.OHLCV:
            bar = self._parse_ohlcv_bar(raw_tick)
            if bar:
                self._bar_store.put(bar)
        elif tick_type == SubscriptionType.ORDER_NOTIFY:
            event = self._parse_order_event(raw_tick)
            if event:
                self._order_bus.publish(event)

    def _classify_tick(self, raw: dict) -> Optional[str]:
        if "order_id" in raw and "status" in raw:
            return SubscriptionType.ORDER_NOTIFY
        if "interval" in raw and "open" in raw and "close" in raw:
            return SubscriptionType.OHLCV
        if "ltp" in raw or "best_bid_price" in raw or "stock_code" in raw:
            return SubscriptionType.QUOTE
        return None

    def _parse_quote_tick(self, raw: dict) -> Optional[TickData]:
        def f(key, default=0.0):
            try:
                v = raw.get(key, default)
                return float(v) if v not in (None, "", "None") else default
            except (ValueError, TypeError):
                return default

        def i(key, default=0):
            return int(f(key, default))

        ltp = f("ltp")
        prev_close = f("prev_close", f("close"))
        change = ltp - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        return TickData(
            stock_token=str(raw.get("stock_token", "")), symbol=str(raw.get("stock_code", "")),
            exchange=str(raw.get("exchange_code", "")), product_type=str(raw.get("product_type", "cash")),
            expiry=str(raw.get("expiry_date", "")), strike=f("strike_price"), right=str(raw.get("right", "")),
            ltp=ltp, ltt=str(raw.get("last_traded_time", "")), ltq=i("last_traded_quantity"),
            volume=i("total_quantity_traded", i("volume")), open_interest=i("open_interest"),
            oi_change=i("change_in_open_interest"), best_bid=f("best_bid_price"), best_bid_qty=i("best_bid_quantity"),
            best_ask=f("best_offer_price", f("best_ask_price")), best_ask_qty=i("best_offer_quantity", i("best_ask_quantity")),
            open=f("open"), high=f("high"), low=f("low"), prev_close=prev_close, change=change, change_pct=change_pct,
            upper_circuit=f("upper_circuit"), lower_circuit=f("lower_circuit"), week_52_high=f("week_52_high"),
            week_52_low=f("week_52_low"), total_buy_qty=i("total_buy_quantity"), total_sell_qty=i("total_sell_quantity"),
            market_depth=[], received_at=time.time()
        )

    def _parse_ohlcv_bar(self, raw: dict) -> Optional[OHLCVBar]:
        def f(key, default=0.0):
            try:
                v = raw.get(key, default)
                return float(v) if v not in (None, "", "None") else default
            except (ValueError, TypeError):
                return default

        return OHLCVBar(str(raw.get("stock_token", "")), str(raw.get("interval", "1minute")),
                        str(raw.get("datetime", raw.get("timestamp", ""))), f("open"), f("high"), f("low"),
                        f("close"), int(f("volume")), int(f("open_interest")), time.time())

    def _parse_order_event(self, raw: dict) -> Optional[OrderEvent]:
        def s(key, default=""):
            return str(raw.get(key, default) or default)

        def f(key):
            try:
                v = raw.get(key, 0)
                return float(v) if v not in (None, "") else 0.0
            except (ValueError, TypeError):
                return 0.0

        def i(key):
            return int(f(key))

        status = s("status").lower()
        if "filled" in status and i("remaining_quantity") == 0:
            event_type = OrderEventType.FILLED
        elif "filled" in status:
            event_type = OrderEventType.PARTIAL
        elif "reject" in status:
            event_type = OrderEventType.REJECTED
        elif "cancel" in status:
            event_type = OrderEventType.CANCELLED
        elif "modify" in status:
            event_type = OrderEventType.MODIFIED
        elif "expired" in status:
            event_type = OrderEventType.EXPIRED
        else:
            event_type = OrderEventType.PLACED
        return OrderEvent(event_type, s("order_id"), s("exchange_order_id"), s("stock_code"), s("exchange_code"),
                          s("product"), s("action"), s("order_type"), i("quantity"), i("filled_quantity"),
                          i("remaining_quantity"), f("price"), f("average_price"), s("status"), s("rejection_reason"),
                          s("order_time", datetime.now().isoformat()), time.time())

    @staticmethod
    def _adjust_depth(stock_token: str, depth: str) -> str:
        parts = stock_token.split(".")
        if len(parts) == 2 and "!" in parts[1]:
            ex_digit = parts[0]
            token_num = parts[1].split("!")[1]
            return f"{ex_digit}.{depth}!{token_num}"
        return stock_token


_live_feed_manager: Optional[LiveFeedManager] = None
_tick_store: Optional[TickStore] = None
_bar_store: Optional[BarStore] = None
_order_bus: Optional[OrderNotificationBus] = None
_token_resolver: Optional[StockTokenResolver] = None
_security_master: Optional[SecurityMasterCache] = None
_init_lock = threading.Lock()


def get_live_feed_manager() -> Optional[LiveFeedManager]:
    return _live_feed_manager


def get_tick_store() -> TickStore:
    global _tick_store
    if _tick_store is None:
        _tick_store = TickStore()
    return _tick_store


def get_bar_store() -> BarStore:
    global _bar_store
    if _bar_store is None:
        _bar_store = BarStore()
    return _bar_store


def get_order_bus() -> OrderNotificationBus:
    global _order_bus
    if _order_bus is None:
        _order_bus = OrderNotificationBus()
    return _order_bus


def get_security_master() -> SecurityMasterCache:
    global _security_master
    if _security_master is None:
        _security_master = SecurityMasterCache()
    return _security_master


def get_token_resolver(breeze: BreezeConnect) -> StockTokenResolver:
    global _token_resolver
    if _token_resolver is None or _token_resolver._breeze is not breeze:
        _token_resolver = StockTokenResolver(get_security_master(), breeze)
    return _token_resolver


def initialize_live_feed(breeze: BreezeConnect, auto_load_security_master: bool = True) -> LiveFeedManager:
    global _live_feed_manager, _tick_store, _bar_store, _order_bus, _security_master
    with _init_lock:
        if _tick_store is None:
            _tick_store = TickStore()
        if _bar_store is None:
            _bar_store = BarStore()
        if _order_bus is None:
            _order_bus = OrderNotificationBus()
        if _security_master is None:
            _security_master = SecurityMasterCache()
            if auto_load_security_master:
                try:
                    _security_master.load()
                except Exception as exc:
                    log.warning(f"Security master load failed: {exc}")
        _live_feed_manager = LiveFeedManager(breeze=breeze, tick_store=_tick_store, bar_store=_bar_store,
                                             order_bus=_order_bus)
        return _live_feed_manager
