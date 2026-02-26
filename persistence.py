"""
SQLite persistence — trades, watchlist, alerts, P&L history, configuration.
Thread-safe singleton. Survives browser refresh, crash, session timeout.
"""

import sqlite3
import json
import threading
import time
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

log = logging.getLogger(__name__)

DB_PATH = Path("data/breeze_trader.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    timestamp TEXT NOT NULL,
    date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    exchange TEXT NOT NULL,
    strike INTEGER,
    option_type TEXT,
    expiry TEXT,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    order_type TEXT,
    status TEXT DEFAULT 'executed',
    pnl REAL DEFAULT 0,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    severity TEXT DEFAULT 'INFO'
);
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    instrument TEXT NOT NULL,
    strike INTEGER,
    option_type TEXT,
    expiry TEXT,
    added_at TEXT NOT NULL,
    notes TEXT,
    UNIQUE(instrument, strike, option_type, expiry)
);
CREATE TABLE IF NOT EXISTS pnl_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    premium_sold REAL DEFAULT 0,
    premium_bought REAL DEFAULT 0,
    num_trades INTEGER DEFAULT 0,
    UNIQUE(date)
);
CREATE TABLE IF NOT EXISTS alerts_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    position_id TEXT,
    acknowledged INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS state_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    order_id TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_pnl_date ON pnl_history(date);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts_log(timestamp);
"""


class TradeDB:
    """Thread-safe singleton SQLite persistence."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(DB_PATH)
        self._local = threading.local()
        self._init_schema()
        self._initialized = True
        log.info(f"TradeDB ready: {self._db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(SCHEMA)
        conn.commit()

    @contextmanager
    def _tx(self):
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ─── Trades ───────────────────────────────────────────────

    def log_trade(self, stock_code: str, exchange: str, strike: int,
                  option_type: str, expiry: str, action: str,
                  quantity: int, price: float, order_type: str = "market",
                  trade_id: str = "", notes: str = "", pnl: float = 0.0) -> bool:
        try:
            if not trade_id:
                trade_id = f"{stock_code}_{strike}_{action}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            today = date.today().isoformat()
            with self._tx() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO trades
                    (trade_id, timestamp, date, stock_code, exchange, strike,
                     option_type, expiry, action, quantity, price, order_type, notes, pnl)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (trade_id, datetime.now().isoformat(), today, stock_code, exchange,
                      strike, option_type, expiry, action, quantity, price, order_type, notes, pnl))
            # Update daily P&L summary
            self._update_daily_pnl(today, action, price, quantity, pnl)
            return True
        except Exception as e:
            log.error(f"log_trade failed: {e}")
            return False

    def _update_daily_pnl(self, date_str: str, action: str, price: float,
                          quantity: int, pnl: float):
        try:
            conn = self._get_conn()
            existing = conn.execute(
                "SELECT * FROM pnl_history WHERE date=?", (date_str,)
            ).fetchone()
            if existing:
                premium_sold = (existing['premium_sold'] or 0) + (price * quantity if action == 'sell' else 0)
                premium_bought = (existing['premium_bought'] or 0) + (price * quantity if action == 'buy' else 0)
                realized = (existing['realized_pnl'] or 0) + pnl
                num_trades = (existing['num_trades'] or 0) + 1
                conn.execute("""
                    UPDATE pnl_history SET premium_sold=?, premium_bought=?,
                    realized_pnl=?, num_trades=? WHERE date=?
                """, (premium_sold, premium_bought, realized, num_trades, date_str))
            else:
                conn.execute("""
                    INSERT INTO pnl_history (date, realized_pnl, premium_sold, premium_bought, num_trades)
                    VALUES (?,?,?,?,?)
                """, (date_str, pnl,
                      price * quantity if action == 'sell' else 0,
                      price * quantity if action == 'buy' else 0, 1))
            conn.commit()
        except Exception as e:
            log.error(f"_update_daily_pnl failed: {e}")

    def get_trades(self, limit: int = 200, stock_code: str = "",
                   date_from: str = "", date_to: str = "") -> List[Dict]:
        try:
            conn = self._get_conn()
            q = "SELECT * FROM trades WHERE 1=1"
            params: list = []
            if stock_code:
                q += " AND stock_code = ?"
                params.append(stock_code)
            if date_from:
                q += " AND date >= ?"
                params.append(date_from)
            if date_to:
                q += " AND date <= ?"
                params.append(date_to)
            q += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(q, params).fetchall()]
        except Exception as e:
            log.error(f"get_trades failed: {e}")
            return []

    def get_trade_summary(self) -> Dict:
        try:
            conn = self._get_conn()
            row = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN action='sell' THEN quantity*price ELSE 0 END) as sold,
                       SUM(CASE WHEN action='buy' THEN quantity*price ELSE 0 END) as bought,
                       SUM(pnl) as total_pnl,
                       COUNT(DISTINCT date) as trading_days
                FROM trades
            """).fetchone()
            return dict(row) if row else {}
        except Exception:
            return {}

    def get_today_trades(self) -> List[Dict]:
        return self.get_trades(limit=100, date_from=date.today().isoformat(),
                               date_to=date.today().isoformat())

    # ─── Activity ─────────────────────────────────────────────

    def log_activity(self, action: str, detail: str = "", severity: str = "INFO") -> bool:
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO activity_log (timestamp, action, detail, severity) VALUES (?,?,?,?)",
                (datetime.now().isoformat(), action, detail, severity)
            )
            conn.commit()
            return True
        except Exception as e:
            log.error(f"log_activity failed: {e}")
            return False

    def get_activities(self, limit: int = 100, action_filter: str = "") -> List[Dict]:
        try:
            conn = self._get_conn()
            q = "SELECT * FROM activity_log WHERE 1=1"
            params: list = []
            if action_filter:
                q += " AND action LIKE ?"
                params.append(f"%{action_filter}%")
            q += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(q, params).fetchall()]
        except Exception:
            return []

    # ─── P&L History ──────────────────────────────────────────

    def get_pnl_history(self, days: int = 30) -> List[Dict]:
        try:
            conn = self._get_conn()
            return [dict(r) for r in conn.execute(
                "SELECT * FROM pnl_history ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()]
        except Exception:
            return []

    def upsert_daily_unrealized(self, unrealized_pnl: float):
        """Update today's unrealized P&L."""
        try:
            today = date.today().isoformat()
            conn = self._get_conn()
            conn.execute("""
                INSERT INTO pnl_history (date, unrealized_pnl) VALUES (?,?)
                ON CONFLICT(date) DO UPDATE SET unrealized_pnl=excluded.unrealized_pnl
            """, (today, unrealized_pnl))
            conn.commit()
        except Exception as e:
            log.error(f"upsert_daily_unrealized failed: {e}")

    # ─── Watchlist ────────────────────────────────────────────

    def add_watchlist_item(self, symbol: str, instrument: str, strike: int = 0,
                           option_type: str = "", expiry: str = "", notes: str = "") -> bool:
        try:
            with self._tx() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO watchlist
                    (symbol, instrument, strike, option_type, expiry, added_at, notes)
                    VALUES (?,?,?,?,?,?,?)
                """, (symbol, instrument, strike, option_type, expiry,
                      datetime.now().isoformat(), notes))
            return True
        except Exception as e:
            log.error(f"add_watchlist_item failed: {e}")
            return False

    def get_watchlist(self) -> List[Dict]:
        try:
            conn = self._get_conn()
            return [dict(r) for r in conn.execute(
                "SELECT * FROM watchlist ORDER BY added_at DESC"
            ).fetchall()]
        except Exception:
            return []

    def remove_watchlist_item(self, item_id: int) -> bool:
        try:
            with self._tx() as conn:
                conn.execute("DELETE FROM watchlist WHERE id=?", (item_id,))
            return True
        except Exception:
            return False

    # ─── Alerts ───────────────────────────────────────────────

    def log_alert(self, level: str, category: str, message: str,
                  position_id: str = "") -> bool:
        try:
            conn = self._get_conn()
            conn.execute("""
                INSERT INTO alerts_log (timestamp, level, category, message, position_id)
                VALUES (?,?,?,?,?)
            """, (datetime.now().isoformat(), level, category, message, position_id))
            conn.commit()
            return True
        except Exception:
            return False

    def get_alerts(self, limit: int = 50, unacknowledged_only: bool = False) -> List[Dict]:
        try:
            conn = self._get_conn()
            q = "SELECT * FROM alerts_log WHERE 1=1"
            if unacknowledged_only:
                q += " AND acknowledged=0"
            q += " ORDER BY timestamp DESC LIMIT ?"
            return [dict(r) for r in conn.execute(q, (limit,)).fetchall()]
        except Exception:
            return []

    def acknowledge_alerts(self):
        try:
            conn = self._get_conn()
            conn.execute("UPDATE alerts_log SET acknowledged=1 WHERE acknowledged=0")
            conn.commit()
        except Exception:
            pass

    # ─── Settings ─────────────────────────────────────────────

    def set_setting(self, key: str, value: Any) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?,?,?)
            """, (key, json.dumps(value), datetime.now().isoformat()))
            conn.commit()
            return True
        except Exception:
            return False

    def get_setting(self, key: str, default: Any = None) -> Any:
        try:
            conn = self._get_conn()
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row['value']) if row else default
        except Exception:
            return default

    def get_all_settings(self) -> Dict:
        try:
            conn = self._get_conn()
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r['key']: json.loads(r['value']) for r in rows}
        except Exception:
            return {}

    # ─── State snapshots ──────────────────────────────────────

    def save_state(self, state: Dict) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("INSERT INTO state_snapshots (timestamp, state_json) VALUES (?,?)",
                         (datetime.now().isoformat(), json.dumps(state, default=str)))
            conn.execute("""
                DELETE FROM state_snapshots WHERE id NOT IN
                (SELECT id FROM state_snapshots ORDER BY timestamp DESC LIMIT 5)
            """)
            conn.commit()
            return True
        except Exception:
            return False

    # ─── Idempotency ──────────────────────────────────────────

    def check_idempotency(self, key: str) -> Optional[str]:
        try:
            conn = self._get_conn()
            cutoff = time.time() - 300
            conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?", (cutoff,))
            conn.commit()
            row = conn.execute("SELECT order_id FROM idempotency_keys WHERE key=?", (key,)).fetchone()
            return row['order_id'] if row else None
        except Exception:
            return None

    def save_idempotency(self, key: str, order_id: str):
        try:
            conn = self._get_conn()
            conn.execute("INSERT OR REPLACE INTO idempotency_keys (key, order_id, created_at) VALUES (?,?,?)",
                         (key, order_id, time.time()))
            conn.commit()
        except Exception as e:
            log.error(f"save_idempotency failed: {e}")

    # ─── Database utilities ───────────────────────────────────

    def get_db_stats(self) -> Dict:
        try:
            conn = self._get_conn()
            stats = {}
            for table in ['trades', 'activity_log', 'watchlist', 'pnl_history', 'alerts_log']:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                stats[table] = row['cnt'] if row else 0
            return stats
        except Exception:
            return {}

    def vacuum(self):
        try:
            conn = self._get_conn()
            conn.execute("VACUUM")
        except Exception:
            pass
