"""Historical data fetch/caching utilities for Breeze PRO."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

log = logging.getLogger(__name__)


class HistoricalCache:
    """Simple in-memory TTL cache for historical candles."""

    def __init__(self, ttl_seconds: int = 600):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, Dict] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(params: Dict) -> str:
        raw = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, params: Dict) -> Optional[pd.DataFrame]:
        key = self._key(params)
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            if (time.time() - item["ts"]) > self.ttl_seconds:
                self._store.pop(key, None)
                return None
            return item["df"].copy()

    def set(self, params: Dict, df: pd.DataFrame) -> None:
        key = self._key(params)
        with self._lock:
            self._store[key] = {"ts": time.time(), "df": df.copy()}

    def stats(self) -> Dict:
        with self._lock:
            now = time.time()
            live = 0
            expired = 0
            for item in self._store.values():
                if (now - item["ts"]) <= self.ttl_seconds:
                    live += 1
                else:
                    expired += 1
            return {
                "entries": len(self._store),
                "live_entries": live,
                "expired_entries": expired,
                "ttl_seconds": self.ttl_seconds,
            }

    def purge_expired(self) -> int:
        with self._lock:
            now = time.time()
            keys = [k for k, v in self._store.items() if (now - v["ts"]) > self.ttl_seconds]
            for k in keys:
                self._store.pop(k, None)
            return len(keys)


_GLOBAL_CACHE = HistoricalCache(ttl_seconds=600)


class HistoricalDataFetcher:
    """Fetches candles through BreezeAPIClient with chunking + cache."""

    def __init__(self, client, cache: HistoricalCache | None = None):
        self.client = client
        self.cache = cache or _GLOBAL_CACHE
        self.last_api_calls = 0

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
    ) -> pd.DataFrame:
        params = {
            "stock_code": stock_code,
            "exchange_code": exchange_code,
            "product_type": product_type,
            "from_date": from_date,
            "to_date": to_date,
            "interval": interval,
            "expiry_date": expiry_date,
            "right": right,
            "strike_price": str(strike_price) if strike_price != "" else "",
        }

        cached = self.cache.get(params)
        if cached is not None:
            self.last_api_calls = 0
            return cached

        chunks = self._build_chunks(from_date, to_date, interval)
        frames: List[pd.DataFrame] = []
        calls = 0

        for start, end in chunks:
            resp = self.client.get_historical_data_v2(
                interval=interval,
                from_date=start,
                to_date=end,
                stock_code=stock_code,
                exchange_code=exchange_code,
                product_type=product_type,
                expiry_date=expiry_date,
                right=right,
                strike_price=str(strike_price) if strike_price != "" else "",
            )
            calls += 1
            frame = self._response_to_df(resp)
            if not frame.empty:
                frames.append(frame)

        self.last_api_calls = calls

        if not frames:
            out = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
            self.cache.set(params, out)
            return out

        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        self.cache.set(params, out)
        return out

    @staticmethod
    def _build_chunks(from_date: str, to_date: str, interval: str) -> List[tuple[str, str]]:
        start = datetime.strptime(from_date[:10], "%Y-%m-%d")
        end = datetime.strptime(to_date[:10], "%Y-%m-%d")

        # Keep API calls low. Daily data: single shot. Intraday: bounded windows.
        if interval == "1day":
            return [(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))]

        window_days = 60 if interval in {"30minute", "5minute"} else 20
        chunks = []
        cur = start
        while cur <= end:
            nxt = min(cur + timedelta(days=window_days - 1), end)
            chunks.append((cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
            cur = nxt + timedelta(days=1)
        return chunks

    @staticmethod
    def _response_to_df(resp: Dict) -> pd.DataFrame:
        if not isinstance(resp, dict) or not resp.get("success"):
            return pd.DataFrame()
        payload = resp.get("data", {})
        rows = payload.get("Success") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Normalize columns across Breeze variants.
        col_map = {
            "datetime": ["datetime", "time", "Date", "date"],
            "open": ["open", "Open"],
            "high": ["high", "High"],
            "low": ["low", "Low"],
            "close": ["close", "Close"],
            "volume": ["volume", "Volume", "vol"],
        }
        normalized = {}
        for canon, aliases in col_map.items():
            for a in aliases:
                if a in df.columns:
                    normalized[canon] = df[a]
                    break
            if canon not in normalized:
                normalized[canon] = pd.Series([None] * len(df))

        out = pd.DataFrame(normalized)
        out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
        for c in ["open", "high", "low", "close", "volume"]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
        out["volume"] = out["volume"].fillna(0)
        return out


def get_historical_cache() -> HistoricalCache:
    return _GLOBAL_CACHE
