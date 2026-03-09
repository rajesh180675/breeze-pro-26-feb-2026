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

import app_config as _C

# IST timezone for converting UTC candle timestamps (Task 1.3)
_IST = _C.IST

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

        # Per spec Appendix C: 1-minute max 3 days, 5-minute/30-minute max 60 days
        if interval == "1minute":
            window_days = 3
        elif interval in {"5minute", "30minute"}:
            window_days = 60
        else:
            window_days = 20
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
            "open_interest": ["open_interest", "OI", "oi", "openInterest"],
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
        out["open_interest"] = pd.to_numeric(out["open_interest"], errors="coerce").fillna(0)
        out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
        out["volume"] = out["volume"].fillna(0)

        # Task 1.3: Convert UTC timestamps from Breeze API to IST for Indian traders
        if out["datetime"].dt.tz is None:
            out["datetime"] = out["datetime"].dt.tz_localize("UTC")
        out["datetime"] = out["datetime"].dt.tz_convert(_IST)

        return out


def get_historical_cache() -> HistoricalCache:
    return _GLOBAL_CACHE


# ---------------------------------------------------------------------------
# Compat aliases used by unit tests (and externally referenced code)
# ---------------------------------------------------------------------------

def _chunk_date_range_compat(self, from_date, to_date, interval: str):  # type: ignore[override]
    """Alias for _build_chunks that also accepts datetime.date objects."""
    from datetime import date as _date
    if isinstance(from_date, _date):
        from_date = from_date.strftime("%Y-%m-%d")
    if isinstance(to_date, _date):
        to_date = to_date.strftime("%Y-%m-%d")
    return HistoricalDataFetcher._build_chunks(from_date, to_date, interval)


def _normalize_records_compat(self, records):  # type: ignore[override]
    """
    Accepts a raw list of candle dicts (as returned in ``data.Success``)
    and returns a normalised DataFrame.  This is the public-facing
    counterpart of the internal ``_response_to_df`` helper.
    """
    if not records:
        import pandas as pd
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "open_interest"])
    fake_resp = {"success": True, "data": {"Success": records}}
    return HistoricalDataFetcher._response_to_df(fake_resp)


# Attach as instance methods so tests can call fetcher._chunk_date_range(...)
HistoricalDataFetcher._chunk_date_range = _chunk_date_range_compat  # type: ignore[attr-defined]
HistoricalDataFetcher._normalize_records = _normalize_records_compat  # type: ignore[attr-defined]
