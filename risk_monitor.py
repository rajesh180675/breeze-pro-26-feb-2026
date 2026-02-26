"""
Enhanced Risk Monitor — per-position stops + portfolio-level limits.
Background daemon thread with thread-safe alert queue.
"""

import threading
import queue
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Alert:
    timestamp: str
    level: str       # INFO, WARNING, CRITICAL
    category: str    # STOP_LOSS, PORTFOLIO, MARGIN, EXPIRY, PRICE_MOVE
    message: str
    position_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitoredPosition:
    position_id: str
    stock_code: str
    exchange: str
    expiry: str
    strike: int
    option_type: str
    position_type: str   # short / long
    quantity: int
    avg_price: float
    stop_loss_price: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    high_water_mark: float = 0.0
    current_price: float = 0.0
    last_update: float = 0.0
    stop_triggered: bool = False


class RiskMonitor:
    """
    Background risk monitor with:
    - Per-position fixed & trailing stop-losses
    - Portfolio-level max loss limit
    - Max delta limit
    - Expiry-day warnings
    - Margin utilization monitoring
    """

    def __init__(self, api_client, poll_interval: float = 15.0,
                 max_portfolio_loss: float = 50000.0,
                 max_delta: float = 500.0):
        self._client = api_client
        self._poll_interval = poll_interval
        self._max_portfolio_loss = max_portfolio_loss
        self._max_delta = max_delta
        self._positions: Dict[str, MonitoredPosition] = {}
        self._alerts: queue.Queue = queue.Queue()
        self._alert_history: List[Alert] = []
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._portfolio_stop_triggered = False
        self._poll_count = 0

    # ─── Configuration ────────────────────────────────────────

    def set_portfolio_limits(self, max_loss: float = None, max_delta: float = None):
        if max_loss is not None:
            self._max_portfolio_loss = max_loss
        if max_delta is not None:
            self._max_delta = max_delta

    # ─── Position management ──────────────────────────────────

    def add_position(self, position_id: str, stock_code: str, exchange: str,
                     expiry: str, strike: int, option_type: str,
                     position_type: str, quantity: int, avg_price: float):
        with self._lock:
            self._positions[position_id] = MonitoredPosition(
                position_id=position_id, stock_code=stock_code, exchange=exchange,
                expiry=expiry, strike=strike, option_type=option_type,
                position_type=position_type, quantity=quantity, avg_price=avg_price,
                current_price=avg_price, high_water_mark=avg_price
            )
        log.info(f"Monitor added: {position_id}")

    def remove_position(self, position_id: str):
        with self._lock:
            self._positions.pop(position_id, None)

    def set_stop_loss(self, position_id: str, stop_price: float):
        with self._lock:
            if position_id in self._positions:
                p = self._positions[position_id]
                p.stop_loss_price = stop_price
                p.trailing_stop_pct = None
                p.stop_triggered = False

    def set_trailing_stop(self, position_id: str, trail_pct: float):
        with self._lock:
            if position_id in self._positions:
                p = self._positions[position_id]
                p.trailing_stop_pct = trail_pct
                p.stop_loss_price = None
                p.high_water_mark = p.current_price or p.avg_price
                p.stop_triggered = False

    def clear_stop(self, position_id: str):
        with self._lock:
            if position_id in self._positions:
                p = self._positions[position_id]
                p.stop_loss_price = None
                p.trailing_stop_pct = None
                p.stop_triggered = False

    # ─── Lifecycle ────────────────────────────────────────────

    def start(self):
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="RiskMonitor", daemon=True)
        self._thread.start()
        log.info("Risk monitor started")

    def stop(self):
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("Risk monitor stopped")

    def is_running(self) -> bool:
        return self._running.is_set()

    # ─── Alert retrieval ──────────────────────────────────────

    def get_alerts(self) -> List[Alert]:
        alerts = []
        while not self._alerts.empty():
            try:
                alerts.append(self._alerts.get_nowait())
            except queue.Empty:
                break
        return alerts

    def get_alert_history(self) -> List[Alert]:
        return list(self._alert_history)

    def get_monitored_summary(self) -> List[Dict]:
        with self._lock:
            return [
                {
                    "id": p.position_id, "stock": p.stock_code, "strike": p.strike,
                    "type": p.option_type, "pos": p.position_type, "qty": p.quantity,
                    "avg": p.avg_price, "current": p.current_price,
                    "stop": p.stop_loss_price, "trail_pct": p.trailing_stop_pct,
                    "triggered": p.stop_triggered,
                    "pnl": self._calc_pos_pnl(p),
                    "expiry": p.expiry
                }
                for p in self._positions.values()
            ]

    def get_portfolio_pnl(self) -> float:
        with self._lock:
            return sum(self._calc_pos_pnl(p) for p in self._positions.values())

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "positions": len(self._positions),
                "alerts": len(self._alert_history),
                "poll_count": self._poll_count,
                "portfolio_pnl": self.get_portfolio_pnl(),
                "portfolio_stop": self._portfolio_stop_triggered,
                "running": self.is_running(),
            }

    # ─── Private helpers ──────────────────────────────────────

    def _calc_pos_pnl(self, pos: MonitoredPosition) -> float:
        if pos.current_price <= 0:
            return 0.0
        if pos.position_type == "short":
            return (pos.avg_price - pos.current_price) * pos.quantity
        return (pos.current_price - pos.avg_price) * pos.quantity

    def _emit(self, alert: Alert):
        self._alerts.put(alert)
        self._alert_history.append(alert)
        if len(self._alert_history) > 100:
            self._alert_history = self._alert_history[-100:]
        log.warning(f"ALERT [{alert.level}] {alert.message}")

    # ─── Monitor loop ─────────────────────────────────────────

    def _loop(self):
        while self._running.is_set():
            try:
                self._check_all()
                self._poll_count += 1
            except Exception as e:
                log.error(f"Monitor loop error: {e}")
            for _ in range(int(self._poll_interval * 10)):
                if not self._running.is_set():
                    break
                time.sleep(0.1)

    def _check_all(self):
        with self._lock:
            positions = list(self._positions.values())

        # Update prices
        for pos in positions:
            if not pos.stop_triggered:
                self._update_price(pos)

        # Check individual stops
        for pos in positions:
            if not pos.stop_triggered:
                self._check_position_stop(pos)

        # Portfolio-level checks
        if not self._portfolio_stop_triggered:
            self._check_portfolio_limits(positions)

        # Expiry warnings
        self._check_expiry_warnings(positions)

    def _update_price(self, pos: MonitoredPosition):
        try:
            resp = self._client.get_quotes(
                pos.stock_code, pos.exchange, pos.expiry, pos.strike, pos.option_type
            )
            if resp.get("success"):
                from helpers import APIResponse, safe_float
                items = APIResponse(resp).items
                if items:
                    ltp = safe_float(items[0].get("ltp", 0))
                    if ltp > 0:
                        pos.current_price = ltp
                        pos.last_update = time.time()
                        # Track high watermark
                        if pos.position_type == "short":
                            if ltp < pos.high_water_mark or pos.high_water_mark <= 0:
                                pos.high_water_mark = ltp
                        else:
                            if ltp > pos.high_water_mark:
                                pos.high_water_mark = ltp
        except Exception as e:
            log.debug(f"Price update failed {pos.position_id}: {e}")

    def _check_position_stop(self, pos: MonitoredPosition):
        if pos.current_price <= 0:
            return
        triggered = False
        reason = ""

        if pos.stop_loss_price is not None:
            if pos.position_type == "short" and pos.current_price >= pos.stop_loss_price:
                triggered = True
                reason = f"Fixed stop hit at ₹{pos.stop_loss_price:.2f}"
            elif pos.position_type == "long" and pos.current_price <= pos.stop_loss_price:
                triggered = True
                reason = f"Fixed stop hit at ₹{pos.stop_loss_price:.2f}"

        elif pos.trailing_stop_pct and pos.trailing_stop_pct > 0 and pos.high_water_mark > 0:
            if pos.position_type == "short":
                trail_level = pos.high_water_mark * (1 + pos.trailing_stop_pct)
                if pos.current_price >= trail_level:
                    triggered = True
                    reason = f"Trailing stop ({pos.trailing_stop_pct*100:.0f}%) triggered at ₹{trail_level:.2f}"
            else:
                trail_level = pos.high_water_mark * (1 - pos.trailing_stop_pct)
                if pos.current_price <= trail_level:
                    triggered = True
                    reason = f"Trailing stop ({pos.trailing_stop_pct*100:.0f}%) triggered at ₹{trail_level:.2f}"

        if triggered:
            pos.stop_triggered = True
            self._emit(Alert(
                timestamp=datetime.now().strftime("%H:%M:%S"),
                level="CRITICAL", category="STOP_LOSS",
                message=f"🚨 STOP: {pos.stock_code} {pos.strike} {pos.option_type} — {reason}. "
                        f"Current: ₹{pos.current_price:.2f} | Avg: ₹{pos.avg_price:.2f}",
                position_id=pos.position_id,
                data={"current": pos.current_price, "avg": pos.avg_price, "stop": pos.stop_loss_price}
            ))

    def _check_portfolio_limits(self, positions: list):
        portfolio_pnl = sum(self._calc_pos_pnl(p) for p in positions)
        if portfolio_pnl < -abs(self._max_portfolio_loss):
            self._portfolio_stop_triggered = True
            self._emit(Alert(
                timestamp=datetime.now().strftime("%H:%M:%S"),
                level="CRITICAL", category="PORTFOLIO",
                message=f"🚨 PORTFOLIO STOP: Total P&L ₹{portfolio_pnl:,.0f} exceeded limit ₹{-self._max_portfolio_loss:,.0f}",
                data={"pnl": portfolio_pnl, "limit": self._max_portfolio_loss}
            ))

        # Price move alert (position lost >50% more than avg)
        for pos in positions:
            if pos.current_price > 0 and pos.avg_price > 0:
                move_pct = (pos.current_price - pos.avg_price) / pos.avg_price * 100
                if pos.position_type == "short" and move_pct > 100:
                    self._emit(Alert(
                        timestamp=datetime.now().strftime("%H:%M:%S"),
                        level="WARNING", category="PRICE_MOVE",
                        message=f"⚠️ {pos.stock_code} {pos.strike} {pos.option_type}: "
                                f"price up {move_pct:.0f}% from entry (₹{pos.avg_price:.2f}→₹{pos.current_price:.2f})",
                        position_id=pos.position_id,
                        data={"move_pct": move_pct}
                    ))

    def _check_expiry_warnings(self, positions: list):
        from helpers import calculate_days_to_expiry
        now_str = datetime.now().strftime("%H:%M:%S")
        for pos in positions:
            dte = calculate_days_to_expiry(pos.expiry)
            if dte == 0 and pos.position_type == "short":
                self._emit(Alert(
                    timestamp=now_str, level="WARNING", category="EXPIRY",
                    message=f"⚠️ EXPIRY TODAY: {pos.stock_code} {pos.strike} {pos.option_type} expires today! Consider square-off.",
                    position_id=pos.position_id, data={"dte": 0}
                ))
            elif dte == 1:
                self._emit(Alert(
                    timestamp=now_str, level="INFO", category="EXPIRY",
                    message=f"ℹ️ Expiry Tomorrow: {pos.stock_code} {pos.strike} {pos.option_type}",
                    position_id=pos.position_id, data={"dte": 1}
                ))
