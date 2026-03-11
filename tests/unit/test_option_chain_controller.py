from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd

from option_chain_controller import (
    apply_option_chain_live_overlay,
    invalidate_option_chain_cache,
    load_cached_option_chain,
    load_compare_option_frames,
    load_option_chain_spot,
    sync_option_chain_live_feed,
)


class _FakeCache:
    def __init__(self):
        self.data = {}
        self.invalidated = []

    def get(self, key, namespace):
        return self.data.get((namespace, key))

    def set(self, key, value, namespace, ttl):
        self.data[(namespace, key)] = value

    def invalidate(self, key, namespace):
        self.invalidated.append((namespace, key))


class _FakeDB:
    def __init__(self):
        self.snapshots = []
        self.intraday = []

    def record_option_chain_snapshot(self, instrument, expiry, rows):
        self.snapshots.append((instrument, expiry, rows))

    def record_option_chain_intraday_snapshot(self, instrument, expiry, rows):
        self.intraday.append((instrument, expiry, rows))


def test_invalidate_option_chain_cache_includes_compare_expiries():
    cache = _FakeCache()
    invalidate_option_chain_cache(cache, "NIFTY", "2026-03-26", ["2026-04-02"])
    assert ("option_chain", "oc_NIFTY_2026-03-26") in cache.invalidated
    assert ("option_chain", "oc_NIFTY_2026-04-02") in cache.invalidated


def test_load_cached_option_chain_uses_cache_and_persists(monkeypatch):
    cache = _FakeCache()
    db = _FakeDB()
    cfg = SimpleNamespace(api_code="NIFTY", exchange="NFO")
    frame = pd.DataFrame([{"strike_price": 22000, "right": "Call", "open_interest": 1000}])
    monkeypatch.setattr("option_chain_controller.fetch_option_chain_snapshot", lambda *args, **kwargs: frame)
    out = load_cached_option_chain(cache, object(), db, "NIFTY", cfg, "2026-03-26", lambda text: nullcontext())
    assert not out.empty
    assert db.snapshots
    cached = load_cached_option_chain(cache, object(), db, "NIFTY", cfg, "2026-03-26", lambda text: nullcontext())
    assert cached.equals(frame)


def test_load_compare_option_frames_keeps_primary_and_secondary():
    first = pd.DataFrame([{"strike_price": 22000}])
    second = pd.DataFrame([{"strike_price": 22100}])
    frames = load_compare_option_frames(lambda expiry: first if expiry.endswith("26") else second, "2026-03-26", ["2026-04-02"])
    assert sorted(frames.keys()) == ["2026-03-26", "2026-04-02"]


def test_load_option_chain_spot_uses_cache_before_client():
    cache = _FakeCache()
    cache.data[("spot", "spot_NIFTY")] = 22123.0
    cfg = SimpleNamespace(api_code="NIFTY", exchange="NSE")
    spot = load_option_chain_spot(cache, object(), cfg, {})
    assert spot == 22123.0


def test_sync_live_feed_and_overlay(monkeypatch):
    session_state = {"oc_ws_tokens_NIFTY_2026-03-26": ["old"]}

    class FakeMgr:
        def __init__(self):
            self.unsubscribed = []

        def unsubscribe_quote(self, token):
            self.unsubscribed.append(token)

    class FakeTickStore:
        def __init__(self):
            self.cleared = []

        def clear_tokens(self, tokens):
            self.cleared.extend(tokens)

    fake_mgr = FakeMgr()
    fake_store = FakeTickStore()
    fake_lf = SimpleNamespace(
        get_live_feed_manager=lambda: fake_mgr,
        get_tick_store=lambda: fake_store,
        unregister_option_chain_tracking=lambda tokens: None,
        register_option_chain_tracking=lambda instrument, token_map: None,
    )
    token_map = sync_option_chain_live_feed(
        fake_lf,
        lambda instrument, expiry, visible, client: {"k1": "new"},
        session_state,
        "NIFTY",
        "2026-03-26",
        "NIFTY",
        [22000],
        object(),
    )
    assert token_map == {"k1": "new"}
    assert session_state["oc_ws_tokens_NIFTY_2026-03-26"] == ["new"]
    assert fake_mgr.unsubscribed == ["old"]
    monkeypatch.setattr("option_chain_controller.merge_live_overlay", lambda df, instrument, expiry, token_map: df.assign(live_overlay=True))
    out = apply_option_chain_live_overlay("🔴 Live WS", pd.DataFrame([{"strike_price": 22000}]), token_map, "NIFTY", "2026-03-26")
    assert bool(out["live_overlay"].iloc[0]) is True
