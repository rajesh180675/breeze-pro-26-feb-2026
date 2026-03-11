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

import live_feed
from historical import HistoricalDataFetcher
from live_feed import (
    DEPTH_L1,
    FeedState,
    HEALTH_STALE_SECONDS,
    LiveFeedManager,
    OptionChainBinding,
    OptionChainMinuteAggregator,
    OrderNotificationBus,
    StockTokenResolver,
    TickStore,
    BarStore,
    get_token_resolver,
    initialize_live_feed,
)


class DummyClient:
    def call_sdk(self, *args, **kwargs):
        return {"success": True, "data": {"Success": []}}


class DummyBreeze:
    def __init__(self):
        self.subscribed = []
        self.unsubscribed = []
        self.connected = False
        self.on_ticks = None

    def subscribe_feeds(self, **kwargs):
        self.subscribed.append(kwargs)

    def unsubscribe_feeds(self, **kwargs):
        self.unsubscribed.append(kwargs)

    def ws_connect(self):
        self.connected = True

    def ws_disconnect(self):
        self.connected = False


def test_historical_chunking_and_normalize():
    fetcher = HistoricalDataFetcher(DummyClient())
    chunks = fetcher._chunk_date_range(date(2025, 1, 1), date(2025, 1, 10), "1minute")
    assert len(chunks) == 4

    df = fetcher._normalize_records(
        [
            {
                "datetime": "2025-01-01T09:15:00+05:30",
                "open": "100",
                "high": "110",
                "low": "90",
                "close": "105",
                "volume": "1000",
                "open_interest": "50",
            }
        ]
    )
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


def test_manual_disconnect_allows_reconnect(monkeypatch):
    starts = []

    class ImmediateThread:
        def __init__(self, *, target, daemon, name):
            self._target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            starts.append(self.name)
            self._target()

    def fake_worker_loop():
        starts.append("worker_ran")

    def fake_connect_with_backoff():
        starts.append("connector_ran")

    breeze = DummyBreeze()
    mgr = LiveFeedManager(
        breeze=breeze,
        tick_store=TickStore(),
        bar_store=BarStore(),
        order_bus=OrderNotificationBus(),
    )
    mgr._state = FeedState.CONNECTED

    mgr.disconnect()

    assert mgr._state == FeedState.DISCONNECTED
    assert breeze.connected is False

    monkeypatch.setattr("live_feed.threading.Thread", ImmediateThread)
    monkeypatch.setattr(mgr, "_worker_loop", fake_worker_loop)
    monkeypatch.setattr(mgr, "_connect_with_backoff", fake_connect_with_backoff)
    mgr.connect()

    assert mgr._state == FeedState.CONNECTING
    assert starts == ["LiveFeedWorker", "worker_ran", "LiveFeedConnector", "connector_ran"]


def test_unsubscribe_quote_uses_matching_market_depth():
    breeze = DummyBreeze()
    mgr = LiveFeedManager(
        breeze=breeze,
        tick_store=TickStore(),
        bar_store=BarStore(),
        order_bus=OrderNotificationBus(),
    )

    assert mgr.subscribe_quote("4.1!2885", get_market_depth=True) is True
    assert mgr.unsubscribe_quote("4.1!2885") is True

    assert breeze.subscribed[-1]["stock_token"] == "4.4!2885"
    assert breeze.unsubscribed[-1]["stock_token"] == "4.4!2885"


def test_get_token_resolver_replaces_cached_resolver_for_new_breeze(monkeypatch):
    monkeypatch.setattr("live_feed._token_resolver", None)
    monkeypatch.setattr("live_feed._security_master", object())

    first_breeze = DummyBreeze()
    second_breeze = DummyBreeze()

    first_resolver = get_token_resolver(first_breeze)
    second_resolver = get_token_resolver(second_breeze)

    assert isinstance(first_resolver, StockTokenResolver)
    assert isinstance(second_resolver, StockTokenResolver)
    assert first_resolver is not second_resolver
    assert first_resolver._breeze is first_breeze
    assert second_resolver._breeze is second_breeze


def test_initialize_live_feed_followed_by_get_token_resolver_uses_latest_breeze(monkeypatch):
    monkeypatch.setattr("live_feed._live_feed_manager", None)
    monkeypatch.setattr("live_feed._tick_store", None)
    monkeypatch.setattr("live_feed._bar_store", None)
    monkeypatch.setattr("live_feed._order_bus", None)
    monkeypatch.setattr("live_feed._token_resolver", None)
    monkeypatch.setattr("live_feed._security_master", object())

    first_breeze = DummyBreeze()
    second_breeze = DummyBreeze()

    initialize_live_feed(first_breeze, auto_load_security_master=False)
    first_resolver = get_token_resolver(first_breeze)

    initialize_live_feed(second_breeze, auto_load_security_master=False)
    second_resolver = get_token_resolver(second_breeze)

    assert first_resolver._breeze is first_breeze
    assert second_resolver._breeze is second_breeze
    assert second_resolver is not first_resolver


def test_connect_with_backoff_restores_subscriptions_after_reconnect(monkeypatch):
    breeze = DummyBreeze()
    mgr = LiveFeedManager(
        breeze=breeze,
        tick_store=TickStore(),
        bar_store=BarStore(),
        order_bus=OrderNotificationBus(),
    )
    restore_calls = []
    wait_calls = []

    def fake_restore_subscriptions():
        restore_calls.append("restored")

    def fake_wait_for_disconnect():
        wait_calls.append("wait")
        if len(wait_calls) == 1:
            mgr._state = FeedState.RECONNECTING
        else:
            mgr._stop_event.set()

    mgr._last_tick_time = 123.0
    monkeypatch.setattr(mgr, "_restore_subscriptions", fake_restore_subscriptions)
    monkeypatch.setattr(mgr, "_wait_for_disconnect", fake_wait_for_disconnect)

    mgr._connect_with_backoff()

    assert mgr._connect_count == 2
    assert restore_calls == ["restored"]
    assert wait_calls == ["wait", "wait"]
    assert mgr._last_tick_time == 0.0


def test_wait_for_disconnect_reconnects_on_stale_feed(monkeypatch):
    monkeypatch.setattr("live_feed.C.is_market_open", lambda: True)
    monkeypatch.setattr("live_feed.time.time", lambda: HEALTH_STALE_SECONDS + 10)
    monkeypatch.setattr("live_feed.time.sleep", lambda _: None)

    breeze = DummyBreeze()
    mgr = LiveFeedManager(
        breeze=breeze,
        tick_store=TickStore(),
        bar_store=BarStore(),
        order_bus=OrderNotificationBus(),
    )
    mgr._state = FeedState.CONNECTED
    mgr._last_tick_time = 1.0

    mgr._wait_for_disconnect()

    assert mgr._state == FeedState.RECONNECTING
    assert breeze.connected is False


def test_option_chain_minute_aggregator_persists_finalized_minute(monkeypatch):
    persisted = []

    class FakeDB:
        def record_option_chain_intraday_snapshot(self, **kwargs):
            persisted.append(kwargs)

    monkeypatch.setattr("persistence.TradeDB", lambda: FakeDB())
    bar_store = BarStore()
    aggregator = OptionChainMinuteAggregator(bar_store)
    aggregator.register_tokens(
        {
            "tok1": OptionChainBinding(
                instrument="NIFTY",
                expiry="2026-03-26",
                strike=22000,
                option_type="CE",
            )
        }
    )

    aggregator.process_tick(
        live_feed.TickData(
            stock_token="tok1",
            symbol="NIFTY",
            exchange="NFO",
            product_type="options",
            expiry="2026-03-26",
            strike=22000,
            right="Call",
            ltp=100,
            ltt="",
            ltq=1,
            volume=1000,
            open_interest=20000,
            oi_change=100,
            best_bid=99,
            best_bid_qty=10,
            best_ask=101,
            best_ask_qty=12,
            open=0,
            high=0,
            low=0,
            prev_close=0,
            change=0,
            change_pct=0,
            upper_circuit=0,
            lower_circuit=0,
            week_52_high=0,
            week_52_low=0,
            total_buy_qty=0,
            total_sell_qty=0,
            market_depth=[],
            received_at=1710148505.0,
        )
    )
    aggregator.process_tick(
        live_feed.TickData(
            stock_token="tok1",
            symbol="NIFTY",
            exchange="NFO",
            product_type="options",
            expiry="2026-03-26",
            strike=22000,
            right="Call",
            ltp=102,
            ltt="",
            ltq=1,
            volume=1200,
            open_interest=20200,
            oi_change=120,
            best_bid=101,
            best_bid_qty=11,
            best_ask=103,
            best_ask_qty=13,
            open=0,
            high=0,
            low=0,
            prev_close=0,
            change=0,
            change_pct=0,
            upper_circuit=0,
            lower_circuit=0,
            week_52_high=0,
            week_52_low=0,
            total_buy_qty=0,
            total_sell_qty=0,
            market_depth=[],
            received_at=1710148535.0,
        )
    )
    aggregator.process_tick(
        live_feed.TickData(
            stock_token="tok1",
            symbol="NIFTY",
            exchange="NFO",
            product_type="options",
            expiry="2026-03-26",
            strike=22000,
            right="Call",
            ltp=103,
            ltt="",
            ltq=1,
            volume=1300,
            open_interest=20300,
            oi_change=130,
            best_bid=102,
            best_bid_qty=12,
            best_ask=104,
            best_ask_qty=14,
            open=0,
            high=0,
            low=0,
            prev_close=0,
            change=0,
            change_pct=0,
            upper_circuit=0,
            lower_circuit=0,
            week_52_high=0,
            week_52_low=0,
            total_buy_qty=0,
            total_sell_qty=0,
            market_depth=[],
            received_at=1710148562.0,
        )
    )
    aggregator.flush_completed(force=True)

    assert len(persisted) == 2
    assert persisted[0]["source"] == "live_1m"
    assert persisted[0]["rows"][0]["ltp"] == 102
    assert persisted[0]["rows"][0]["bar_high"] == 102
