import os
from pathlib import Path

import json
import sys
import types
import pytest
import pandas as pd

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:  # noqa: D401
        """Stub BreezeConnect for offline deterministic tests."""

        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

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
    build_option_chain_ladder,
    summarize_alert_commentary_payload,
    enrich_option_chain,
    load_replay_frame,
)
from option_chain_workspace import (
    build_replay_delta_oi_frame,
    option_chain_chart_supports_selection,
    resolve_monitored_strike_defaults,
    resolve_selected_strike,
)
from option_chain_alerts import build_commentary, evaluate_alerts
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
    normalized_dataset = build_multi_expiry_dataset(expiry_frames, "open_interest", normalization_mode="ATM Offset", spot=22020)
    strip = build_expiry_strip(expiry_frames, 22020, lambda expiry: 7 if expiry.endswith("26") else 14)
    oi_fig = build_multi_expiry_oi_figure(expiry_frames, normalization_mode="ATM Offset", spot=22020)
    iv_fig = build_multi_expiry_iv_smile_figure(expiry_frames, normalization_mode="ATM %", spot=22020)

    assert not dataset.empty
    assert not normalized_dataset.empty
    assert sorted(dataset["expiry"].unique().tolist()) == ["2099-03-26", "2099-04-02"]
    assert len(strip) == 2
    assert len(oi_fig.data) == 2
    assert len(iv_fig.data) == 2


def test_watchlist_backed_ladder_state_and_sticky_atm(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    assert db.sync_option_chain_watchlist("NIFTY", "2099-03-26", [22000, 22100]) is True
    persisted = db.get_option_chain_watchlist("NIFTY", "2099-03-26")
    df = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2099-03-26", 22020, include_greeks=False)
    ladder = build_option_chain_ladder(df, 22020, pinned_strikes=persisted, selected_strike=22000, sticky_atm=True)
    assert persisted == [22000, 22100]
    assert ladder.iloc[0]["strike"] == 22000
    assert int(ladder.loc[ladder["strike"] == 22100, "is_pinned"].iloc[0]) == 1


def test_page_flow_helpers_cover_replay_selection_normalization_and_watchlist_restore(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    assert db.sync_option_chain_watchlist("NIFTY", "2099-03-26", [22000, 22100]) is True
    restored = resolve_monitored_strike_defaults([], db.get_option_chain_watchlist("NIFTY", "2099-03-26"), [21900, 22000, 22100])
    selected = resolve_selected_strike(None, [21900, 22000, 22100], 22020)
    assert restored == [22000, 22100]
    assert selected == 22000

    change_df = pd.DataFrame(
        [
            {"strike": 22000, "option_type": "CE", "open_interest_change": 1200},
            {"strike": 22100, "option_type": "PE", "open_interest_change": -500},
        ]
    )
    delta_view = build_replay_delta_oi_frame(change_df, pd.DataFrame())
    assert list(delta_view["right"]) == ["Call", "Put"]
    assert option_chain_chart_supports_selection("Compare OI") is True
    assert option_chain_chart_supports_selection("Expected Move") is False

    front = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2099-03-26", 22020, include_greeks=False)
    nxt = enrich_option_chain(_fixture("option_chain_expiry_day.json"), "NIFTY", "2099-04-02", 22020, include_greeks=False)
    dataset = build_multi_expiry_dataset({"2099-03-26": front, "2099-04-02": nxt}, "open_interest", normalization_mode="ATM %", spot=22020)
    assert "comparison_axis" in dataset.columns


def test_alert_and_commentary_page_payload_is_deterministic():
    previous_df = enrich_option_chain(_fixture("option_chain_balanced.json"), "NIFTY", "2099-03-26", 22020, include_greeks=False)
    current_df = enrich_option_chain(_fixture("option_chain_put_heavy.json"), "NIFTY", "2099-03-26", 22020, include_greeks=False)
    alerts = evaluate_alerts(
        current_df,
        previous_df=previous_df,
        spot=22020,
        expiry="2099-03-26",
        monitored_strikes=[22000],
        snapshot_ts="2099-03-11T09:20:00",
    )
    commentary = build_commentary(current_df, alerts, spot=22020, expiry="2099-03-26")
    payload = summarize_alert_commentary_payload(alerts, commentary)
    assert payload["alerts"]
    assert payload["commentary"]
    joined = " ".join(payload["commentary"]).lower()
    assert "support" in joined or "wall" in joined
