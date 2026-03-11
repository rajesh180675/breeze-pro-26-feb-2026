import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd

from option_chain_service import (
    build_expiry_strip,
    build_option_chain_ladder,
    enrich_option_chain,
    filter_option_chain,
    merge_live_overlay,
    summarize_chain,
)


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def test_filter_and_ladder_build_are_stable():
    df = _fixture("option_chain_balanced.json")
    filtered = filter_option_chain(df, atm=22000, strikes_per_side=1, show_all=False)
    assert set(filtered["strike_price"]) == {21900, 22000, 22100}
    enriched = enrich_option_chain(filtered, "NIFTY", "2026-03-26", 22020, include_greeks=False)
    ladder = build_option_chain_ladder(enriched, 22020, pinned_strikes=[22000])
    assert list(ladder.columns[:3]) == ["call_ltp", "call_oi", "call_oi_change"]
    assert 22000 in ladder["strike"].tolist()
    assert ladder.loc[ladder["strike"] == 22000, "is_pinned"].iloc[0] == 1


def test_merge_live_overlay_updates_quote_fields(monkeypatch):
    df = _fixture("option_chain_balanced.json").iloc[:2].copy()
    cfg = SimpleNamespace(exchange="NFO", api_code="NIFTY")
    monkeypatch.setattr("option_chain_service.C.get_instrument", lambda instrument: cfg)

    class FakeTickStore:
        def get_latest(self, token):
            if token == "tok1":
                return SimpleNamespace(
                    ltp=999.0,
                    best_bid=998.0,
                    best_ask=1000.0,
                    best_bid_qty=50,
                    best_ask_qty=60,
                    volume=4444,
                    open_interest=5555,
                    oi_change=333,
                    received_at=0.0,
                )
            return None

    fake_live_feed = ModuleType("live_feed")
    fake_live_feed.get_tick_store = lambda: FakeTickStore()
    monkeypatch.setitem(sys.modules, "live_feed", fake_live_feed)
    token_map = {"NFO|NIFTY|options|2026-03-26|21900.0|call": "tok1"}
    out = merge_live_overlay(df, "NIFTY", "2026-03-26", token_map)
    call_row = out[out["right"] == "Call"].iloc[0]
    assert call_row["ltp"] == 999.0
    assert call_row["open_interest"] == 5555


def test_expiry_strip_and_summary():
    cur = _fixture("option_chain_balanced.json")
    nxt = _fixture("option_chain_expiry_day.json")
    summary = summarize_chain(cur, 22010, 7)
    assert summary["atm"] == 22000
    strip = build_expiry_strip({"2026-03-26": cur, "2026-04-02": nxt}, 22010, lambda expiry: 7 if expiry.endswith("26") else 14)
    assert len(strip) == 2
    assert strip[0]["expiry"] == "2026-03-26"
