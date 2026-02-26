"""Historical data engine for Breeze PRO."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pytz

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breeze_api import BreezeAPIClient

log = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

MARKET_MINUTES_PER_DAY = 375
MARKET_DAYS_PER_WEEK = 5

MAX_RANGE_BY_INTERVAL: Dict[str, int] = {
    "1second": 1,
    "1minute": 3,
    "5minute": 10,
    "30minute": 60,
    "1day": 1500,
}

CACHE_TTL_BY_INTERVAL: Dict[str, int] = {
    "1second": 3600,
    "1minute": 3600,
    "5minute": 3600,
    "30minute": 86400,
    "1day": 86400,
}

HIST_CACHE_DB_PATH = Path("data/hist_cache.db")

HIST_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_cache (
    cache_key TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    candle_count INTEGER NOT NULL,
    interval TEXT NOT NULL,
    stock_code TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hist_fetched ON historical_cache(fetched_at);
CREATE INDEX IF NOT EXISTS idx_hist_stock ON historical_cache(stock_code, interval);
"""


class HistoricalCache:
    _instance: Optional["HistoricalCache"] = None
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
        HIST_CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(HIST_CACHE_DB_PATH)
        self._local = threading.local()
        self._init_schema()
        self._initialized = True

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-65536")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        self._conn().executescript(HIST_SCHEMA)
        self._conn().commit()

    def make_key(
        self,
        stock_code: str,
        exchange: str,
        product_type: str,
        interval: str,
        expiry: str,
        right: str,
        strike: str,
        from_date: str,
        to_date: str,
    ) -> str:
        parts = [stock_code, exchange, product_type, interval, expiry, right, strike, from_date, to_date]
        return "|".join(parts).replace(" ", "").lower()

    def get(self, cache_key: str) -> Optional[pd.DataFrame]:
        try:
            row = self._conn().execute(
                "SELECT data_json, fetched_at, ttl_seconds FROM historical_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            data_json, fetched_at, ttl = row
            if time.time() - fetched_at > ttl:
                return None
            records = json.loads(data_json)
            if not records:
                return pd.DataFrame()
            df = pd.DataFrame(records)
            df["datetime"] = pd.to_datetime(df["datetime"])
            return df
        except Exception as exc:
            log.warning("HistoricalCache.get error: %s", exc)
            return None

    def put(self, cache_key: str, df: pd.DataFrame, ttl: int, interval: str, stock_code: str) -> None:
        try:
            serializable = df.copy()
            serializable["datetime"] = serializable["datetime"].astype(str)
            records = serializable.to_dict(orient="records")
            data_json = json.dumps(records)
            self._conn().execute(
                """
                INSERT OR REPLACE INTO historical_cache
                (cache_key, data_json, fetched_at, ttl_seconds, candle_count, interval, stock_code)
                VALUES (?,?,?,?,?,?,?)
                """,
                (cache_key, data_json, time.time(), ttl, len(df), interval, stock_code),
            )
            self._conn().commit()
        except Exception as exc:
            log.warning("HistoricalCache.put error: %s", exc)

    def purge_expired(self) -> int:
        now = time.time()
        cursor = self._conn().execute(
            "DELETE FROM historical_cache WHERE fetched_at + ttl_seconds < ?",
            (now,),
        )
        self._conn().commit()
        return cursor.rowcount

    def stats(self) -> Dict:
        row = self._conn().execute(
            """
            SELECT COUNT(*) as n, SUM(LENGTH(data_json)) as bytes,
                   MIN(fetched_at) as oldest
            FROM historical_cache
            """
        ).fetchone()
        return {
            "entry_count": row[0],
            "total_bytes": row[1] or 0,
            "oldest_entry": datetime.fromtimestamp(row[2]).isoformat() if row[2] else None,
        }


class HistoricalDataFetcher:
    def __init__(self, api_client: "BreezeAPIClient", max_fetch_workers: int = 4):
        self._client = api_client
        self._cache = HistoricalCache()
        self._max_workers = max_fetch_workers

    def fetch(
        self,
        stock_code: str,
        exchange_code: str,
        product_type: str,
        from_date: str,
        to_date: str,
        interval: str,
        expiry_date: str = "",
        right: str = "",
        strike_price: str = "",
        use_cache: bool = True,
        use_v2: bool = True,
    ) -> pd.DataFrame:
        if interval not in MAX_RANGE_BY_INTERVAL:
            raise ValueError(f"Invalid interval: {interval!r}. Valid: {list(MAX_RANGE_BY_INTERVAL.keys())}")

        from_dt = _parse_date(from_date)
        to_dt = _parse_date(to_date)
        if from_dt > to_dt:
            raise ValueError(f"from_date ({from_date}) must be ≤ to_date ({to_date})")

        cache_key = self._cache.make_key(
            stock_code,
            exchange_code,
            product_type,
            interval,
            expiry_date,
            right,
            strike_price,
            from_date,
            to_date,
        )
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Historical cache HIT: %s", cache_key[:40])
                return cached

        chunks = self._chunk_date_range(from_dt, to_dt, interval)
        all_dfs: List[pd.DataFrame] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(
                    self._fetch_chunk,
                    stock_code,
                    exchange_code,
                    product_type,
                    interval,
                    expiry_date,
                    right,
                    strike_price,
                    chunk_from,
                    chunk_to,
                    use_v2,
                ): (chunk_from, chunk_to)
                for chunk_from, chunk_to in chunks
            }
            for fut in as_completed(futures):
                chunk_from, chunk_to = futures[fut]
                try:
                    df_chunk = fut.result()
                    if df_chunk is not None and not df_chunk.empty:
                        all_dfs.append(df_chunk)
                except Exception as exc:
                    log.warning("Chunk %s→%s failed: %s", chunk_from, chunk_to, exc)

        if not all_dfs:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "open_interest"])

        result = pd.concat(all_dfs, ignore_index=True)
        result = result.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

        if use_cache:
            ttl = CACHE_TTL_BY_INTERVAL.get(interval, 3600)
            self._cache.put(cache_key, result, ttl, interval, stock_code)
        return result

    def fetch_latest_n_bars(
        self,
        stock_code: str,
        exchange_code: str,
        product_type: str,
        interval: str,
        n_bars: int = 200,
        expiry_date: str = "",
        right: str = "",
        strike_price: str = "",
    ) -> pd.DataFrame:
        to_dt = datetime.now(IST).date()
        days_needed = self._bars_to_calendar_days(n_bars, interval)
        from_dt = to_dt - timedelta(days=days_needed)
        return self.fetch(
            stock_code=stock_code,
            exchange_code=exchange_code,
            product_type=product_type,
            from_date=from_dt.isoformat(),
            to_date=to_dt.isoformat(),
            interval=interval,
            expiry_date=expiry_date,
            right=right,
            strike_price=strike_price,
        )

    def _chunk_date_range(self, from_dt: date, to_dt: date, interval: str) -> List[Tuple[date, date]]:
        max_days = MAX_RANGE_BY_INTERVAL[interval]
        chunks: List[Tuple[date, date]] = []
        current = from_dt
        while current <= to_dt:
            chunk_end = min(current + timedelta(days=max_days - 1), to_dt)
            chunks.append((current, chunk_end))
            current = chunk_end + timedelta(days=1)
        return chunks

    def _fetch_chunk(
        self,
        stock_code: str,
        exchange_code: str,
        product_type: str,
        interval: str,
        expiry_date: str,
        right: str,
        strike_price: str,
        from_dt: date,
        to_dt: date,
        use_v2: bool,
    ) -> Optional[pd.DataFrame]:
        from_iso = from_dt.strftime("%Y-%m-%dT00:00:00.000Z")
        to_iso = to_dt.strftime("%Y-%m-%dT23:59:59.000Z")
        expiry_iso = _convert_to_breeze_datetime(expiry_date) if expiry_date else ""

        if use_v2:
            resp = self._client.call_sdk(
                "get_historical_data_v2",
                retryable=True,
                interval=interval,
                from_date=from_iso,
                to_date=to_iso,
                stock_code=stock_code,
                exchange_code=exchange_code,
                product_type=product_type,
                expiry_date=expiry_iso,
                right=right.lower() if right else "",
                strike_price=str(strike_price) if strike_price else "",
            )
        else:
            resp = self._client.call_sdk(
                "get_historical_data",
                retryable=True,
                interval=interval,
                from_date=from_iso,
                to_date=to_iso,
                stock_code=stock_code,
                exchange_code=exchange_code,
                product_type=product_type,
                expiry_date=expiry_iso,
                right=right.lower() if right else "",
                strike_price=str(strike_price) if strike_price else "",
            )

        if not resp.get("success"):
            log.warning("Historical fetch failed: %s", resp.get("message"))
            return None

        success_data = resp.get("data", {})
        if isinstance(success_data, dict):
            records = success_data.get("Success") or []
        else:
            records = success_data if isinstance(success_data, list) else []
        if not records:
            return None
        return self._normalize_records(records)

    @staticmethod
    def _normalize_records(records: List[Dict]) -> pd.DataFrame:
        rows = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            dt_raw = rec.get("datetime") or rec.get("date_time") or rec.get("date") or rec.get("timestamp") or ""
            if not dt_raw:
                continue
            try:
                dt = pd.to_datetime(dt_raw)
                if dt.tzinfo is None:
                    dt = IST.localize(dt)
            except Exception:
                continue

            def f(keys, default=0.0):
                for key in keys:
                    val = rec.get(key)
                    if val is not None and val != "":
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            pass
                return default

            rows.append(
                {
                    "datetime": dt,
                    "open": f(["open"]),
                    "high": f(["high"]),
                    "low": f(["low"]),
                    "close": f(["close"]),
                    "volume": int(f(["volume", "total_quantity_traded", "qty"])),
                    "open_interest": int(f(["open_interest", "oi"])),
                }
            )

        if not rows:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "open_interest"])
        return pd.DataFrame(rows)

    @staticmethod
    def _bars_to_calendar_days(n_bars: int, interval: str) -> int:
        bars_per_day = {
            "1second": MARKET_MINUTES_PER_DAY * 60,
            "1minute": MARKET_MINUTES_PER_DAY,
            "5minute": MARKET_MINUTES_PER_DAY // 5,
            "30minute": MARKET_MINUTES_PER_DAY // 30,
            "1day": 1,
        }
        bpd = bars_per_day.get(interval, 375)
        trading_days = max(1, (n_bars + bpd - 1) // bpd)
        calendar_days = int(trading_days * 1.4 * 7 / MARKET_DAYS_PER_WEEK) + 7
        return calendar_days


def _parse_date(date_str: str) -> date:
    if isinstance(date_str, date):
        return date_str
    return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()


def _convert_to_breeze_datetime(date_str: str) -> str:
    """Convert YYYY-MM-DD to Breeze expiry format YYYY-MM-DDT06:00:00.000Z."""
    if not date_str:
        return ""
    d = str(date_str)[:10]
    return f"{d}T06:00:00.000Z"
