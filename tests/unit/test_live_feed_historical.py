import sys
import types

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")
    class BreezeConnect:  # noqa: D401
        """Stub BreezeConnect for tests."""
        pass
    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

from datetime import date

import pandas as pd

from historical import HistoricalDataFetcher
from live_feed import (
    DEPTH_L1,
    FeedState,
    LiveFeedManager,
    OrderNotificationBus,
    TickStore,
    BarStore,
)


class DummyClient:
    def call_sdk(self, *args, **kwargs):
        return {"success": True, "data": {"Success": []}}


class DummyBreeze:
    def __init__(self):
        self.subscribed = []
        self.connected = False
        self.on_ticks = None

    def subscribe_feeds(self, **kwargs):
        self.subscribed.append(kwargs)

    def ws_connect(self):
        self.connected = True

    def ws_disconnect(self):
        self.connected = False


def test_historical_chunking_and_normalize():
    fetcher = HistoricalDataFetcher(DummyClient())
    chunks = fetcher._chunk_date_range(date(2025, 1, 1), date(2025, 1, 10), "1minute")
    assert len(chunks) == 4

    df = fetcher._normalize_records([
        {
            "datetime": "2025-01-01T09:15:00+05:30",
            "open": "100",
            "high": "110",
            "low": "90",
            "close": "105",
            "volume": "1000",
            "open_interest": "50",
        }
    ])
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["datetime", "open", "high", "low", "close", "volume", "open_interest"]
    assert float(df.iloc[0]["close"]) == 105.0


def test_live_feed_health_and_restore_subscriptions(monkeypatch):
    monkeypatch.setattr("live_feed.C.is_market_open", lambda: True)

    breeze = DummyBreeze()
    mgr = LiveFeedManager(
        breeze=breeze,
        tick_store=TickStore(),
        bar_store=BarStore(),
        order_bus=OrderNotificationBus(),
    )

    assert mgr.subscribe_quote("4.1!2885", get_market_depth=False) is True
    assert breeze.subscribed[-1]["stock_token"] == f"4.{DEPTH_L1}!2885"

    mgr._state = FeedState.CONNECTED
    mgr._last_tick_time = 0
    stats = mgr.get_health_stats()
    assert stats["total_subscriptions"] >= 1
    assert stats["state"] == FeedState.CONNECTED
    assert stats["is_stale"] is False

    mgr._restore_subscriptions()
    assert len(breeze.subscribed) >= 2
