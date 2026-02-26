"""GTT (Good Till Triggered) order management for Breeze PRO."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

import app_config as C
from breeze_api import BreezeAPIClient, convert_to_breeze_datetime
from persistence import TradeDB

log = logging.getLogger(__name__)


class GTTType(str, Enum):
    SINGLE = "single"
    THREE_LEG = "three_leg"


class GTTStatus(str, Enum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class GTTLegType(str, Enum):
    ENTRY = "entry"
    TARGET = "target"
    STOPLOSS = "stoploss"


@dataclass
class GTTLeg:
    gtt_leg_type: GTTLegType
    action: str
    trigger_price: str
    limit_price: str
    order_type: str = "limit"
    quantity: str = ""


@dataclass
class GTTOrderRequest:
    exchange_code: str
    stock_code: str
    product: str
    quantity: str
    expiry_date: str
    right: str
    strike_price: str
    gtt_type: GTTType
    index_or_stock: str
    trade_date: str
    fresh_order_action: str = ""
    fresh_order_price: str = ""
    fresh_order_type: str = "limit"
    order_details: List[GTTLeg] = field(default_factory=list)


@dataclass
class GTTOrderRecord:
    gtt_order_id: str
    gtt_type: GTTType
    status: GTTStatus
    instrument: str
    exchange_code: str
    stock_code: str
    expiry: str
    strike: int
    right: str
    quantity: int
    product: str
    fresh_action: str
    entry_price: float
    target_price: float
    target_trigger_price: float
    stoploss_price: float
    stoploss_trigger_price: float
    trade_date: str
    created_at: str
    triggered_at: Optional[str] = None
    trigger_leg: Optional[str] = None
    cancelled_at: Optional[str] = None
    notes: str = ""
    raw_response: str = ""


class GTTValidationError(Exception):
    pass


def validate_gtt_request(req: GTTOrderRequest) -> Tuple[bool, str]:
    if req.exchange_code not in ("NFO", "BFO", "NSE", "BSE"):
        return False, f"Invalid exchange_code: {req.exchange_code}"
    if not req.stock_code:
        return False, "stock_code is required"

    try:
        qty = int(req.quantity)
        if qty <= 0:
            return False, f"quantity must be positive, got {qty}"
    except ValueError:
        return False, f"quantity must be numeric, got {req.quantity!r}"

    if req.product == "options":
        if not req.right:
            return False, "right (call/put) is required for options GTT"
        if not req.strike_price:
            return False, "strike_price is required for options GTT"

    if req.gtt_type == GTTType.THREE_LEG:
        if not req.fresh_order_action:
            return False, "fresh_order_action is required for three-leg GTT"
        if not req.fresh_order_price:
            return False, "fresh_order_price (entry price) is required for three-leg GTT"
        if len(req.order_details) < 2:
            return False, "Three-leg GTT requires exactly 2 order_details (target + stoploss)"

        leg_types = {leg.gtt_leg_type for leg in req.order_details}
        if GTTLegType.TARGET not in leg_types:
            return False, "Three-leg GTT requires a TARGET leg in order_details"
        if GTTLegType.STOPLOSS not in leg_types:
            return False, "Three-leg GTT requires a STOPLOSS leg in order_details"

        if req.fresh_order_action == "sell":
            entry_price = float(req.fresh_order_price)
            for leg in req.order_details:
                trigger = float(leg.trigger_price)
                limit = float(leg.limit_price)
                if leg.gtt_leg_type == GTTLegType.TARGET and trigger >= entry_price:
                    return False, f"Target trigger ({trigger}) must be below entry price ({entry_price}) for a sell entry"
                if leg.gtt_leg_type == GTTLegType.STOPLOSS:
                    if trigger <= entry_price:
                        return False, f"Stop-loss trigger ({trigger}) must be above entry price ({entry_price}) for a sell entry"
                    if limit < trigger:
                        return False, f"Stop-loss limit price ({limit}) should be ≥ trigger ({trigger})"

    if req.gtt_type == GTTType.SINGLE and not req.order_details:
        return False, "Single-leg GTT requires at least 1 order_detail"
    return True, ""


GTT_SCHEMA = """
CREATE TABLE IF NOT EXISTS gtt_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gtt_order_id TEXT UNIQUE NOT NULL,
    gtt_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    instrument TEXT NOT NULL,
    exchange_code TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    expiry TEXT NOT NULL,
    strike INTEGER NOT NULL,
    right TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    product TEXT NOT NULL,
    fresh_action TEXT DEFAULT '',
    entry_price REAL DEFAULT 0,
    target_price REAL DEFAULT 0,
    target_trigger_price REAL DEFAULT 0,
    stoploss_price REAL DEFAULT 0,
    stoploss_trigger_price REAL DEFAULT 0,
    trade_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    triggered_at TEXT,
    trigger_leg TEXT,
    cancelled_at TEXT,
    notes TEXT DEFAULT '',
    raw_response TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_gtt_status ON gtt_orders(status);
CREATE INDEX IF NOT EXISTS idx_gtt_created ON gtt_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gtt_exchange ON gtt_orders(exchange_code, status);
"""


class GTTManager:
    SYNC_INTERVAL_SECONDS = 60

    def __init__(self, client: BreezeAPIClient, db: TradeDB):
        self._client = client
        self._db = db
        self._ensure_schema()
        self._sync_thread: Optional[threading.Thread] = None
        self._sync_stop = threading.Event()
        self._lock = threading.Lock()
        self._last_sync: Optional[datetime] = None

    def _ensure_schema(self) -> None:
        conn = self._db._get_conn()
        conn.executescript(GTT_SCHEMA)
        conn.commit()

    def place_single_leg(self, req: GTTOrderRequest) -> Dict:
        is_valid, err = validate_gtt_request(req)
        if not is_valid:
            return {"success": False, "message": err, "data": {}}

        expiry_iso = convert_to_breeze_datetime(req.expiry_date)
        trade_date_iso = convert_to_breeze_datetime(req.trade_date)
        leg = req.order_details[0]
        order_details = [{
            "action": leg.action.lower(),
            "trigger_price": str(leg.trigger_price),
            "order_type": leg.order_type.lower(),
            "price": str(leg.limit_price),
        }]
        breeze_gtt_type = "STOPLOSS" if leg.gtt_leg_type == GTTLegType.STOPLOSS else "PROFIT"

        resp = self._client.call_sdk(
            "gtt_single_leg_place_order",
            retryable=False,
            exchange_code=req.exchange_code,
            stock_code=req.stock_code,
            product=req.product,
            quantity=str(req.quantity),
            expiry_date=expiry_iso,
            right=req.right.lower(),
            strike_price=str(req.strike_price),
            gtt_type=breeze_gtt_type,
            index_or_stock=req.index_or_stock,
            trade_date=trade_date_iso,
            order_details=order_details,
        )

        if resp.get("success"):
            gtt_id = self._extract_gtt_order_id(resp) or str(uuid.uuid4())
            record = GTTOrderRecord(
                gtt_order_id=gtt_id,
                gtt_type=GTTType.SINGLE,
                status=GTTStatus.ACTIVE,
                instrument=req.stock_code,
                exchange_code=req.exchange_code,
                stock_code=req.stock_code,
                expiry=req.expiry_date,
                strike=int(float(req.strike_price)),
                right=req.right,
                quantity=int(req.quantity),
                product=req.product,
                fresh_action=leg.action,
                entry_price=0.0,
                target_price=float(leg.limit_price) if leg.gtt_leg_type == GTTLegType.TARGET else 0.0,
                target_trigger_price=float(leg.trigger_price) if leg.gtt_leg_type == GTTLegType.TARGET else 0.0,
                stoploss_price=float(leg.limit_price) if leg.gtt_leg_type == GTTLegType.STOPLOSS else 0.0,
                stoploss_trigger_price=float(leg.trigger_price) if leg.gtt_leg_type == GTTLegType.STOPLOSS else 0.0,
                trade_date=req.trade_date,
                created_at=datetime.now().isoformat(),
                notes=f"Single-leg {breeze_gtt_type}",
                raw_response=str(resp),
            )
            self._save_record(record)
        return resp

    def place_three_leg(self, req: GTTOrderRequest) -> Dict:
        is_valid, err = validate_gtt_request(req)
        if not is_valid:
            return {"success": False, "message": err, "data": {}}

        expiry_iso = convert_to_breeze_datetime(req.expiry_date)
        trade_date_iso = convert_to_breeze_datetime(req.trade_date)
        order_details: List[Dict] = []
        target_leg = None
        stoploss_leg = None
        for leg in req.order_details:
            d = {
                "action": leg.action.lower(),
                "trigger_price": str(leg.trigger_price),
                "order_type": leg.order_type.lower(),
                "price": str(leg.limit_price),
            }
            if leg.quantity:
                d["quantity"] = str(leg.quantity)
            order_details.append(d)
            if leg.gtt_leg_type == GTTLegType.TARGET:
                target_leg = leg
            elif leg.gtt_leg_type == GTTLegType.STOPLOSS:
                stoploss_leg = leg

        resp = self._client.call_sdk(
            "gtt_three_leg_place_order",
            retryable=False,
            exchange_code=req.exchange_code,
            stock_code=req.stock_code,
            product=req.product,
            quantity=str(req.quantity),
            expiry_date=expiry_iso,
            right=req.right.lower(),
            strike_price=str(req.strike_price),
            gtt_type="THREE_LEG",
            fresh_order_action=req.fresh_order_action.lower(),
            fresh_order_price=str(req.fresh_order_price),
            fresh_order_type=req.fresh_order_type.lower(),
            index_or_stock=req.index_or_stock,
            trade_date=trade_date_iso,
            order_details=order_details,
        )
        if resp.get("success"):
            gtt_id = self._extract_gtt_order_id(resp) or str(uuid.uuid4())
            self._save_record(
                GTTOrderRecord(
                    gtt_order_id=gtt_id,
                    gtt_type=GTTType.THREE_LEG,
                    status=GTTStatus.ACTIVE,
                    instrument=req.stock_code,
                    exchange_code=req.exchange_code,
                    stock_code=req.stock_code,
                    expiry=req.expiry_date,
                    strike=int(float(req.strike_price)),
                    right=req.right,
                    quantity=int(req.quantity),
                    product=req.product,
                    fresh_action=req.fresh_order_action,
                    entry_price=float(req.fresh_order_price),
                    target_price=float(target_leg.limit_price) if target_leg else 0.0,
                    target_trigger_price=float(target_leg.trigger_price) if target_leg else 0.0,
                    stoploss_price=float(stoploss_leg.limit_price) if stoploss_leg else 0.0,
                    stoploss_trigger_price=float(stoploss_leg.trigger_price) if stoploss_leg else 0.0,
                    trade_date=req.trade_date,
                    created_at=datetime.now().isoformat(),
                    notes="Three-leg OCO",
                    raw_response=str(resp),
                )
            )
        return resp

    def modify_single_leg(self, exchange_code: str, gtt_order_id: str, gtt_type: str, order_details: List[Dict]) -> Dict:
        resp = self._client.call_sdk("gtt_single_leg_modify_order", retryable=False, exchange_code=exchange_code, gtt_order_id=gtt_order_id, gtt_type=gtt_type, order_details=order_details)
        if resp.get("success"):
            self._update_status(gtt_order_id, GTTStatus.ACTIVE)
        return resp

    def modify_three_leg(self, exchange_code: str, gtt_order_id: str, gtt_type: str, order_details: List[Dict]) -> Dict:
        return self._client.call_sdk("gtt_three_leg_modify_order", retryable=False, exchange_code=exchange_code, gtt_order_id=gtt_order_id, gtt_type=gtt_type, order_details=order_details)

    def cancel_single_leg(self, exchange_code: str, gtt_order_id: str) -> Dict:
        resp = self._client.call_sdk("gtt_single_leg_cancel_order", retryable=False, exchange_code=exchange_code, gtt_order_id=gtt_order_id)
        if resp.get("success"):
            self._update_status(gtt_order_id, GTTStatus.CANCELLED, cancelled_at=datetime.now().isoformat())
        return resp

    def cancel_three_leg(self, exchange_code: str, gtt_order_id: str) -> Dict:
        resp = self._client.call_sdk("gtt_three_leg_cancel_order", retryable=False, exchange_code=exchange_code, gtt_order_id=gtt_order_id)
        if resp.get("success"):
            self._update_status(gtt_order_id, GTTStatus.CANCELLED, cancelled_at=datetime.now().isoformat())
        return resp

    def cancel(self, gtt_order_id: str) -> Dict:
        record = self._load_record(gtt_order_id)
        if not record:
            return {"success": False, "message": f"GTT {gtt_order_id} not found in local DB"}
        if record.status != GTTStatus.ACTIVE:
            return {"success": False, "message": f"GTT {gtt_order_id} is not active (status: {record.status})"}
        return self.cancel_single_leg(record.exchange_code, gtt_order_id) if record.gtt_type == GTTType.SINGLE else self.cancel_three_leg(record.exchange_code, gtt_order_id)

    def get_order_book(self, exchange_code: str = "NFO", from_date: str = "", to_date: str = "") -> Dict:
        from_iso = convert_to_breeze_datetime(from_date) if from_date else convert_to_breeze_datetime("2020-01-01")
        to_iso = convert_to_breeze_datetime(to_date) if to_date else convert_to_breeze_datetime(datetime.now().strftime("%Y-%m-%d"))
        return self._client.call_sdk("gtt_order_book", retryable=True, exchange_code=exchange_code, from_date=from_iso, to_date=to_iso)

    def get_active_gtts(self) -> List[GTTOrderRecord]:
        return self._load_records(status_filter=GTTStatus.ACTIVE)

    def get_all_gtts(self, limit: int = 200) -> List[GTTOrderRecord]:
        return self._load_records(limit=limit)

    def start_sync(self) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._sync_stop.clear()
        self._sync_thread = threading.Thread(target=self._sync_loop, name="GTTSyncThread", daemon=True)
        self._sync_thread.start()

    def stop_sync(self) -> None:
        self._sync_stop.set()

    def sync_with_api(self, exchange_code: str = "NFO") -> int:
        resp = self.get_order_book(exchange_code=exchange_code)
        if not resp.get("success"):
            return 0
        api_orders = (resp.get("data", {}) or {}).get("Success") or []
        if not isinstance(api_orders, list):
            return 0
        changes = 0
        for api_order in api_orders:
            if not isinstance(api_order, dict):
                continue
            gtt_id = str(api_order.get("gtt_order_id", ""))
            if not gtt_id:
                continue
            api_status_raw = str(api_order.get("status", "")).lower()
            if "trigger" in api_status_raw:
                new_status = GTTStatus.TRIGGERED
            elif "cancel" in api_status_raw:
                new_status = GTTStatus.CANCELLED
            elif "expire" in api_status_raw:
                new_status = GTTStatus.EXPIRED
            else:
                new_status = GTTStatus.ACTIVE
            local = self._load_record(gtt_id)
            if local and local.status != new_status:
                self._update_status(gtt_id, new_status, triggered_at=datetime.now().isoformat() if new_status == GTTStatus.TRIGGERED else None)
                changes += 1
        self._last_sync = datetime.now()
        return changes

    def _sync_loop(self) -> None:
        while not self._sync_stop.is_set():
            if C.is_market_open():
                try:
                    self.sync_with_api("NFO")
                except Exception as e:
                    log.error(f"GTT sync error: {e}")
            self._sync_stop.wait(timeout=self.SYNC_INTERVAL_SECONDS)

    @staticmethod
    def _extract_gtt_order_id(resp: Dict) -> Optional[str]:
        """Extract GTT order ID from API response."""
        success = resp.get("data", {})
        if isinstance(success, dict):
            success = success.get("Success") or success
        if isinstance(success, dict):
            return str(success.get("gtt_order_id", ""))
        if isinstance(success, list) and success:
            return str(success[0].get("gtt_order_id", ""))
        return None

    # ── SQLite persistence ────────────────────────────────────────────────────

    def _save_record(self, record: GTTOrderRecord) -> None:
        try:
            with self._db._tx() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO gtt_orders (
                        gtt_order_id, gtt_type, status, instrument, exchange_code,
                        stock_code, expiry, strike, right, quantity, product,
                        fresh_action, entry_price, target_price, target_trigger_price,
                        stoploss_price, stoploss_trigger_price, trade_date,
                        created_at, triggered_at, trigger_leg, cancelled_at, notes, raw_response
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        record.gtt_order_id,
                        record.gtt_type.value,
                        record.status.value,
                        record.instrument,
                        record.exchange_code,
                        record.stock_code,
                        record.expiry,
                        record.strike,
                        record.right,
                        record.quantity,
                        record.product,
                        record.fresh_action,
                        record.entry_price,
                        record.target_price,
                        record.target_trigger_price,
                        record.stoploss_price,
                        record.stoploss_trigger_price,
                        record.trade_date,
                        record.created_at,
                        record.triggered_at,
                        record.trigger_leg,
                        record.cancelled_at,
                        record.notes,
                        record.raw_response,
                    ),
                )
        except Exception as e:
            log.error(f"GTT save_record failed: {e}")

    def _load_record(self, gtt_order_id: str) -> Optional[GTTOrderRecord]:
        try:
            row = self._db._get_conn().execute(
                "SELECT * FROM gtt_orders WHERE gtt_order_id=?", (gtt_order_id,)
            ).fetchone()
            return self._row_to_record(row) if row else None
        except Exception as e:
            log.error(f"GTT load_record failed: {e}")
            return None

    def _load_records(
        self,
        status_filter: Optional[GTTStatus] = None,
        limit: int = 200,
    ) -> List[GTTOrderRecord]:
        try:
            query = "SELECT * FROM gtt_orders"
            params: tuple = ()
            if status_filter:
                query += " WHERE status=?"
                params = (status_filter.value,)
            query += " ORDER BY created_at DESC LIMIT ?"
            params = params + (limit,)
            rows = self._db._get_conn().execute(query, params).fetchall()
            return [self._row_to_record(row) for row in rows if row]
        except Exception as e:
            log.error(f"GTT load_records failed: {e}")
            return []

    def _update_status(
        self,
        gtt_order_id: str,
        status: GTTStatus,
        triggered_at: Optional[str] = None,
        cancelled_at: Optional[str] = None,
    ) -> None:
        try:
            with self._db._tx() as conn:
                conn.execute(
                    """UPDATE gtt_orders SET status=?, triggered_at=?,
                       cancelled_at=? WHERE gtt_order_id=?""",
                    (status.value, triggered_at, cancelled_at, gtt_order_id),
                )
        except Exception as e:
            log.error(f"GTT update_status failed: {e}")

    @staticmethod
    def _row_to_record(row) -> GTTOrderRecord:
        """Convert an sqlite3.Row to GTTOrderRecord."""
        d = dict(row)
        return GTTOrderRecord(
            gtt_order_id=d["gtt_order_id"],
            gtt_type=GTTType(d["gtt_type"]),
            status=GTTStatus(d["status"]),
            instrument=d["instrument"],
            exchange_code=d["exchange_code"],
            stock_code=d["stock_code"],
            expiry=d["expiry"],
            strike=d["strike"],
            right=d["right"],
            quantity=d["quantity"],
            product=d["product"],
            fresh_action=d.get("fresh_action", ""),
            entry_price=d.get("entry_price", 0.0) or 0.0,
            target_price=d.get("target_price", 0.0) or 0.0,
            target_trigger_price=d.get("target_trigger_price", 0.0) or 0.0,
            stoploss_price=d.get("stoploss_price", 0.0) or 0.0,
            stoploss_trigger_price=d.get("stoploss_trigger_price", 0.0) or 0.0,
            trade_date=d.get("trade_date", ""),
            created_at=d.get("created_at", ""),
            triggered_at=d.get("triggered_at"),
            trigger_leg=d.get("trigger_leg"),
            cancelled_at=d.get("cancelled_at"),
            notes=d.get("notes", ""),
            raw_response=d.get("raw_response", ""),
        )
