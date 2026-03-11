import os
from pathlib import Path

import json
import pytest
import pandas as pd

import app_config as C
from breeze_api import BreezeAPIClient
import persistence as persistence_mod
pytest.importorskip("plotly")
from option_chain_charts import (
    build_multi_expiry_iv_smile_figure,
    build_multi_expiry_oi_figure,
    build_skew_shift_replay_figure,
)
from option_chain_service import (
    build_expiry_strip,
    build_multi_expiry_dataset,
    build_window_change_dataset,
    enrich_option_chain,
    load_replay_frame,
)
from persistence import TradeDB

pytestmark = pytest.mark.integration


def _fixture(name: str) -> pd.DataFrame:
    path = Path(__file__).resolve().parents[1] / "fixtures" / name
    return pd.DataFrame(json.loads(path.read_text()))


def _fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "integration_option_chain.db"
    monkeypatch.setattr(persistence_mod, "DB_PATH", db_file)
    TradeDB._instance = None
    return TradeDB()


def _client():
    required = ["BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing integration credentials: {', '.join(missing)}")
    c = BreezeAPIClient(os.environ["BREEZE_API_KEY"], os.environ["BREEZE_API_SECRET"])
    assert c.connect(os.environ["BREEZE_SESSION_TOKEN"]).get("success")
    return c


def test_fetch_live_nifty_chain_structure():
    client = _client()
    cfg = C.get_instrument("NIFTY")
    expiry = C.get_next_expiries("NIFTY", 1)[0]
    resp = client.get_option_chain(cfg.api_code, cfg.exchange, expiry)
    assert resp.get("success") is True
    data = resp.get("data", {})
    assert isinstance(data, dict)
    assert isinstance(data.get("Success"), list)


def test_replay_pipeline_uses_persisted_intraday_snapshots(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    for snapshot_ts, ltp, oi, iv in (
        ("2026-03-11T09:15:00", 100, 1000, 0.18),
        ("2026-03-11T09:20:00", 108, 1250, 0.21),
    ):
        db.record_option_chain_intraday_snapshot(
            instrument="NIFTY",
            expiry="2026-03-26",
            trade_date="2026-03-11",
            snapshot_ts=snapshot_ts,
            rows=[
                {"strike_price": 22000, "right": "Call", "ltp": ltp, "volume": oi // 2, "open_interest": oi, "oi_change": oi - 900, "iv": iv},
                {"strike_price": 22000, "right": "Put", "ltp": ltp + 12, "volume": oi // 3, "open_interest": oi + 200, "oi_change": oi - 850, "iv": iv + 0.01},
            ],
        )

    replay_frame = load_replay_frame(db, "NIFTY", "2026-03-26", "2026-03-11T09:18:00")
    assert not replay_frame.empty
    assert replay_frame["snapshot_ts"].nunique() == 1
    assert replay_frame["snapshot_ts"].iloc[0] == "2026-03-11T09:15:00"

    change_df = build_window_change_dataset(db, "NIFTY", "2026-03-26", "2026-03-11T09:20:00", "5m")
    assert not change_df.empty
    assert set(change_df["open_interest_change"]) == {250, 250}

    replay_chart_df = pd.DataFrame(db.get_option_chain_intraday_snapshots("NIFTY", expiry="2026-03-26", trade_date="2026-03-11"))
    replay_fig = build_skew_shift_replay_figure(replay_chart_df)
    assert len(replay_fig.data) == 1


def test_compare_expiry_pipeline_builds_overlays_from_enriched_frames():
    front = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2099-03-26", 22020, include_greeks=False)
    next_expiry = enrich_option_chain(_fixture("option_chain_expiry_day.json"), "NIFTY", "2099-04-02", 22020, include_greeks=False)
    expiry_frames = {"2099-03-26": front, "2099-04-02": next_expiry}

    dataset = build_multi_expiry_dataset(expiry_frames, "open_interest")
    strip = build_expiry_strip(expiry_frames, 22020, lambda expiry: 7 if expiry.endswith("26") else 14)
    oi_fig = build_multi_expiry_oi_figure(expiry_frames)
    iv_fig = build_multi_expiry_iv_smile_figure(expiry_frames)

    assert not dataset.empty
    assert sorted(dataset["expiry"].unique().tolist()) == ["2099-03-26", "2099-04-02"]
    assert len(strip) == 2
    assert len(oi_fig.data) == 2
    assert len(iv_fig.data) == 2
