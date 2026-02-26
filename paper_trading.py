"""Paper trading simulator for Breeze PRO."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class PaperOrder:
    order_id: str
    stock_code: str
    exchange_code: str
    product: str
    action: str
    quantity: int
    order_type: str
    price: float
    stoploss: float
    expiry_date: str
    right: str
    strike_price: str
    status: str
    fill_price: float = 0.0
    fill_time: str = ""
    placed_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PaperPosition:
    stock_code: str
    exchange_code: str
    right: str
    strike_price: str
    expiry_date: str
    product: str
    quantity: int
    average_price: float
    realized_pnl: float = 0.0


class PaperTradingEngine:
    FILL_CHECK_INTERVAL = 5

    def __init__(self, live_client, tick_store=None, initial_capital: float = 500_000.0):
        self._client = live_client
        self._tick_store = tick_store
        self._orders: Dict[str, PaperOrder] = {}
        self._positions: Dict[str, PaperPosition] = {}
        self._capital = initial_capital
        self._used_capital = 0.0
        self._enabled = False
        self._fill_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._trade_log: List[Dict] = []
        self._realized_pnl = 0.0

    def enable(self) -> None:
        if self._enabled:
            return
        self._enabled = True
        self._stop_event.clear()
        self._fill_thread = threading.Thread(target=self._fill_loop, name="PaperFillLoop", daemon=True)
        self._fill_thread.start()
        log.info("Paper trading mode ENABLED")

    def disable(self) -> None:
        self._enabled = False
        self._stop_event.set()
        log.info("Paper trading mode DISABLED")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def place_order(self, stock_code: str, exchange_code: str, product: str, action: str, quantity: str,
                    order_type: str, price: str = "", stoploss: str = "0", expiry_date: str = "",
                    right: str = "", strike_price: str = "", **kwargs) -> Dict:
        order_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        qty = int(float(quantity))
        price_f = float(price) if str(price).strip() else 0.0
        sl_f = float(stoploss) if str(stoploss).strip() else 0.0

        order = PaperOrder(
            order_id=order_id,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product=product,
            action=action.lower(),
            quantity=qty,
            order_type=order_type.lower(),
            price=price_f,
            stoploss=sl_f,
            expiry_date=expiry_date,
            right=right.lower(),
            strike_price=str(strike_price),
            status="PENDING",
        )

        with self._lock:
            self._orders[order_id] = order

        if order.order_type == "market":
            fill_price = self._get_market_price(stock_code, exchange_code, expiry_date, right, strike_price, price_f)
            self._fill_order(order, fill_price)

        return {
            "success": True,
            "data": {"Success": [{"order_id": order_id}]},
            "message": "Paper order placed",
            "error_code": None,
        }

    def get_paper_orders(self, status: Optional[str] = None) -> List[PaperOrder]:
        with self._lock:
            orders = list(self._orders.values())
        if status:
            orders = [o for o in orders if o.status == status]
        return sorted(orders, key=lambda o: o.placed_at, reverse=True)

    def get_paper_positions(self) -> List[PaperPosition]:
        with self._lock:
            return list(self._positions.values())

    def get_paper_summary(self) -> Dict:
        positions = self.get_paper_positions()
        orders = self.get_paper_orders()
        total_realized = self._realized_pnl
        return {
            "capital": self._capital,
            "used_capital": self._used_capital,
            "open_positions": len([p for p in positions if p.quantity != 0]),
            "total_orders": len(orders),
            "filled_orders": len([o for o in orders if o.status == "FILLED"]),
            "realized_pnl": round(total_realized, 2),
        }

    def reset(self) -> None:
        with self._lock:
            self._orders.clear()
            self._positions.clear()
            self._used_capital = 0.0
            self._trade_log.clear()
            self._realized_pnl = 0.0

    def _get_market_price(self, stock_code, exchange_code, expiry_date, right, strike_price, fallback: float) -> float:
        if self._tick_store and hasattr(self._tick_store, "get_all_latest"):
            try:
                for tick in self._tick_store.get_all_latest().values():
                    if getattr(tick, "symbol", "") == stock_code and str(getattr(tick, "right", "")).lower() == str(right).lower():
                        return float(getattr(tick, "ltp", 0) or 0)
            except Exception:
                pass
        try:
            if right:
                resp = self._client.get_quotes(
                    stock_code=stock_code,
                    exchange_code=exchange_code,
                    product_type="options" if right else "cash",
                    expiry_date=expiry_date,
                    right=right,
                    strike_price=str(strike_price),
                )
            else:
                resp = self._client.get_quotes(stock_code=stock_code, exchange_code=exchange_code, product_type="cash")
            if resp.get("success"):
                sd = (resp.get("data", {}) or {}).get("Success") or []
                if isinstance(sd, list) and sd:
                    return float(sd[0].get("ltp", fallback) or fallback)
        except Exception:
            pass
        return fallback if fallback > 0 else 10.0

    def _fill_order(self, order: PaperOrder, fill_price: float) -> None:
        with self._lock:
            order.fill_price = fill_price
            order.fill_time = datetime.now().isoformat()
            order.status = "FILLED"
            self._update_position(order, fill_price)
            self._trade_log.append({
                "order_id": order.order_id,
                "action": order.action,
                "qty": order.quantity,
                "fill_price": fill_price,
                "timestamp": order.fill_time,
            })

    def _update_position(self, order: PaperOrder, fill_price: float) -> None:
        key = f"{order.stock_code}|{order.expiry_date}|{order.strike_price}|{order.right}"
        pos = self._positions.get(key) or PaperPosition(
            stock_code=order.stock_code,
            exchange_code=order.exchange_code,
            right=order.right,
            strike_price=order.strike_price,
            expiry_date=order.expiry_date,
            product=order.product,
            quantity=0,
            average_price=0.0,
        )

        qty_delta = order.quantity if order.action == "buy" else -order.quantity
        if pos.quantity == 0:
            pos.average_price = fill_price
        elif (pos.quantity > 0 and qty_delta > 0) or (pos.quantity < 0 and qty_delta < 0):
            total_qty = abs(pos.quantity) + abs(qty_delta)
            pos.average_price = (abs(pos.quantity) * pos.average_price + abs(qty_delta) * fill_price) / max(1, total_qty)
        else:
            matched = min(abs(qty_delta), abs(pos.quantity))
            if order.action == "buy":
                pnl = (pos.average_price - fill_price) * matched
            else:
                pnl = (fill_price - pos.average_price) * matched
            pos.realized_pnl += pnl
            self._realized_pnl += pnl

        pos.quantity += qty_delta
        if pos.quantity == 0:
            self._positions.pop(key, None)
        else:
            self._positions[key] = pos

    def _fill_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                pending = [o for o in self._orders.values() if o.status == "PENDING"]
            for order in pending:
                if order.order_type not in ("limit", "stoploss"):
                    continue
                current_price = self._get_market_price(order.stock_code, order.exchange_code, order.expiry_date,
                                                       order.right, order.strike_price, 0.0)
                if current_price <= 0:
                    continue
                fill_condition = False
                if order.order_type == "limit":
                    fill_condition = ((order.action == "buy" and current_price <= order.price) or
                                      (order.action == "sell" and current_price >= order.price))
                elif order.stoploss > 0:
                    fill_condition = ((order.action == "buy" and current_price >= order.stoploss) or
                                      (order.action == "sell" and current_price <= order.stoploss))
                if fill_condition:
                    fill_price = order.price if order.order_type == "limit" else current_price
                    self._fill_order(order, fill_price)
            self._stop_event.wait(timeout=self.FILL_CHECK_INTERVAL)
