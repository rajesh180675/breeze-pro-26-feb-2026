"""
SQLite persistence — trades, watchlist, alerts, P&L history, configuration.
Thread-safe singleton. Survives browser refresh, crash, session timeout.
"""

import sqlite3
import json
import threading
import time
import logging
import io
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

import pandas as pd

log = logging.getLogger(__name__)

DB_PATH = Path("data/breeze_trader.db")

# ── Task 4.3: Database Migration Framework ────────────────────
SCHEMA_VERSION = 5


class DBMigrator:
    """Incremental schema migration runner (Task 4.3).

    Each migration is keyed by version number.  ``run()`` applies only
    migrations whose version is greater than the current stored version.
    """

    MIGRATIONS: Dict[int, str] = {
        1: "ALTER TABLE trades ADD COLUMN notes TEXT",
        2: "CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)",
        3: (
            "CREATE TABLE IF NOT EXISTS market_regime_log ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  timestamp TEXT NOT NULL,"
            "  regime TEXT NOT NULL,"
            "  confidence REAL DEFAULT 0,"
            "  signals_json TEXT"
            ")"
        ),
        4: "ALTER TABLE alerts_log ADD COLUMN dispatched_channels TEXT",
        5: "CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol)",
    }

    @staticmethod
    def _ensure_version_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )

    @staticmethod
    def _get_version(conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute(
                "SELECT MAX(version) as v FROM schema_version"
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0

    @staticmethod
    def _set_version(conn: sqlite3.Connection, version: int) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, datetime.now().isoformat()),
        )

    def run(self, conn: sqlite3.Connection) -> int:
        """Apply pending migrations.  Returns count of migrations applied."""
        self._ensure_version_table(conn)
        current = self._get_version(conn)
        applied = 0
        for ver in sorted(self.MIGRATIONS.keys()):
            if ver > current:
                sql = self.MIGRATIONS[ver]
                try:
                    conn.execute(sql)
                    self._set_version(conn, ver)
                    applied += 1
                    log.info("Applied migration v%d", ver)
                except sqlite3.OperationalError as exc:
                    # Column/index may already exist from initial schema
                    if "duplicate column" in str(exc).lower() or "already exists" in str(exc).lower():
                        self._set_version(conn, ver)
                        log.info("Migration v%d skipped (already applied): %s", ver, exc)
                    else:
                        log.error("Migration v%d failed: %s", ver, exc)
                        raise
        if applied:
            conn.commit()
        return applied

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
CREATE TABLE IF NOT EXISTS nse_holidays (
    iso_date    TEXT PRIMARY KEY,
    description TEXT    NOT NULL DEFAULT '',
    year        INTEGER NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'nse_api',
    fetched_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nse_holidays_year ON nse_holidays(year);
CREATE TABLE IF NOT EXISTS account_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_name TEXT UNIQUE NOT NULL,
    api_key TEXT NOT NULL,
    totp_secret TEXT DEFAULT '',
    broker TEXT DEFAULT 'ICICI',
    is_active INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_used TEXT
);
CREATE TABLE IF NOT EXISTS basket_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    instrument TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    legs_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used TEXT,
    use_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS market_regime_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    regime TEXT NOT NULL,
    confidence REAL DEFAULT 0,
    signals_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_pnl_date ON pnl_history(date);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol);
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
        # Task 4.3: Run incremental migrations after base schema
        try:
            migrator = DBMigrator()
            applied = migrator.run(conn)
            if applied:
                log.info("DBMigrator applied %d migration(s)", applied)
        except Exception as exc:
            log.error("DBMigrator failed: %s", exc)

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
            with self._tx() as conn:
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


# ── Innovation 3: Basket Order Templates ───────────────────────

class BasketTemplateDB:
    """Persist and retrieve basket order templates (Innovation 3)."""

    def __init__(self, db: "TradeDB"):
        self._db = db

    def save_template(
        self,
        name: str,
        instrument: str,
        strategy_type: str,
        legs_json: str,
    ) -> bool:
        """Save or update a basket template."""
        try:
            with self._db._tx() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO basket_templates "
                    "(name, instrument, strategy_type, legs_json, created_at, "
                    " last_used, use_count) "
                    "VALUES (?, ?, ?, ?, "
                    "  COALESCE((SELECT created_at FROM basket_templates WHERE name=?), ?), "
                    "  (SELECT last_used FROM basket_templates WHERE name=?), "
                    "  COALESCE((SELECT use_count FROM basket_templates WHERE name=?), 0))",
                    (
                        name, instrument, strategy_type, legs_json,
                        name, datetime.now().isoformat(),
                        name, name,
                    ),
                )
            return True
        except Exception as e:
            log.error("save_template failed: %s", e)
            return False

    def get_templates(self, instrument: str = "") -> List[Dict]:
        """List saved basket templates, optionally filtered by instrument."""
        try:
            conn = self._db._get_conn()
            if instrument:
                rows = conn.execute(
                    "SELECT * FROM basket_templates WHERE instrument=? ORDER BY last_used DESC",
                    (instrument,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM basket_templates ORDER BY last_used DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_template(self, name: str) -> Optional[Dict]:
        try:
            row = self._db._get_conn().execute(
                "SELECT * FROM basket_templates WHERE name=?", (name,)
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def use_template(self, name: str) -> None:
        """Mark template as used (update last_used + increment use_count)."""
        try:
            with self._db._tx() as conn:
                conn.execute(
                    "UPDATE basket_templates SET last_used=?, use_count=use_count+1 WHERE name=?",
                    (datetime.now().isoformat(), name),
                )
        except Exception as e:
            log.error("use_template failed: %s", e)

    def delete_template(self, name: str) -> bool:
        try:
            with self._db._tx() as conn:
                conn.execute("DELETE FROM basket_templates WHERE name=?", (name,))
            return True
        except Exception:
            return False


class AccountProfileDB:
    """Manage multiple account credential profiles."""

    def __init__(self, db: TradeDB):
        self._db = db

    def save_profile(self, profile_name: str, api_key: str, totp_secret: str = "", broker: str = "ICICI") -> None:
        now = datetime.now().isoformat()
        with self._db._tx() as conn:
            existing = conn.execute(
                "SELECT created_at FROM account_profiles WHERE profile_name=?", (profile_name,)
            ).fetchone()
            created_at = existing["created_at"] if existing and existing["created_at"] else now
            conn.execute(
                """
                INSERT OR REPLACE INTO account_profiles
                (profile_name, api_key, totp_secret, broker, is_active, created_at, last_used)
                VALUES (?, ?, ?, ?,
                    COALESCE((SELECT is_active FROM account_profiles WHERE profile_name=?), 0),
                    ?,
                    COALESCE((SELECT last_used FROM account_profiles WHERE profile_name=?), NULL)
                )
                """,
                (profile_name, api_key, totp_secret, broker, profile_name, created_at, profile_name),
            )

    def get_profiles(self) -> List[Dict]:
        rows = self._db._get_conn().execute(
            "SELECT * FROM account_profiles ORDER BY profile_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_profile(self, profile_name: str) -> Optional[Dict]:
        row = self._db._get_conn().execute(
            "SELECT * FROM account_profiles WHERE profile_name=?",
            (profile_name,),
        ).fetchone()
        return dict(row) if row else None

    def delete_profile(self, profile_name: str) -> None:
        with self._db._tx() as conn:
            conn.execute("DELETE FROM account_profiles WHERE profile_name=?", (profile_name,))

    def set_active(self, profile_name: str) -> None:
        with self._db._tx() as conn:
            conn.execute("UPDATE account_profiles SET is_active=0")
            conn.execute(
                "UPDATE account_profiles SET is_active=1, last_used=? WHERE profile_name=?",
                (datetime.now().isoformat(), profile_name),
            )

    def get_active_profile(self) -> Optional[Dict]:
        row = self._db._get_conn().execute(
            "SELECT * FROM account_profiles WHERE is_active=1 LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def export_trades_for_tax(
    db: TradeDB,
    financial_year: str,
    format: str = "csv",
) -> bytes:
    """Export trade history for one financial year as CSV or Excel bytes."""
    year_start_str, year_end_str = financial_year.split("-")
    fy_start = f"{year_start_str}-04-01"
    fy_end = f"20{year_end_str}-03-31"

    trades = db.get_trades(limit=100000, date_from=fy_start, date_to=fy_end)
    if not trades:
        return b""

    rows = []
    for trade in trades:
        quantity = float(trade.get("quantity", 0) or 0)
        price = float(trade.get("price", 0) or 0)
        value = quantity * price
        rows.append(
            {
                "Trade Date": trade.get("date", ""),
                "Settlement No": trade.get("settlement_no", ""),
                "Order ID": trade.get("trade_id", ""),
                "Stock Code": trade.get("stock_code", ""),
                "Exchange": trade.get("exchange", ""),
                "Right": trade.get("option_type", ""),
                "Strike": trade.get("strike", ""),
                "Expiry": (trade.get("expiry") or "")[:10],
                "Action": str(trade.get("action", "")).upper(),
                "Quantity": int(quantity),
                "Price": price,
                "Value": value,
                "STT": trade.get("stt", ""),
                "Brokerage": trade.get("brokerage", ""),
                "Net Amount": trade.get("net_amount", value),
            }
        )

    df = pd.DataFrame(rows)
    export_format = format.lower().strip()
    if export_format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8")

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Trades", index=False)
        summary = (
            df.groupby("Action")
            .agg(total_quantity=("Quantity", "sum"), total_value=("Value", "sum"))
            .reset_index()
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)
    return buf.getvalue()
