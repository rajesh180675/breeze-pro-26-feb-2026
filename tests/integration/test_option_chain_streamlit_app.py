import pytest
from streamlit.testing.v1 import AppTest


pytestmark = pytest.mark.integration


def _streamlit_option_chain_script(db_path: str, front_fixture: str, next_fixture: str) -> str:
    return f"""
import json
import sys
import types
import importlib.util
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

if "breeze_connect" not in sys.modules:
    stub = types.ModuleType("breeze_connect")

    class BreezeConnect:
        pass

    stub.BreezeConnect = BreezeConnect
    sys.modules["breeze_connect"] = stub

import persistence as persistence_mod
from persistence import TradeDB
import option_chain_controller as occ

front_rows = json.loads(Path(r"{front_fixture}").read_text())
next_rows = json.loads(Path(r"{next_fixture}").read_text())


def make_frame(expiry: str) -> pd.DataFrame:
    rows = front_rows if expiry == "2026-03-26" else next_rows
    return pd.DataFrame(rows)


def bump_rows(rows, ltp_delta: float, oi_delta: float):
    bumped = []
    for row in rows:
        current = dict(row)
        current["ltp"] = float(current.get("ltp", 0) or 0) + ltp_delta
        current["open_interest"] = float(current.get("open_interest", 0) or 0) + oi_delta
        current["oi_change"] = float(current.get("oi_change", 0) or 0) + (oi_delta / 2.0)
        bumped.append(current)
    return bumped


persistence_mod.DB_PATH = Path(r"{db_path}")
TradeDB._instance = None
db = TradeDB()
db.record_option_chain_intraday_snapshot(
    "NIFTY",
    "2026-03-26",
    front_rows,
    snapshot_ts="2026-03-11T09:15:00",
    trade_date="2026-03-11",
)
db.record_option_chain_intraday_snapshot(
    "NIFTY",
    "2026-03-26",
    bump_rows(front_rows, ltp_delta=5.0, oi_delta=250.0),
    snapshot_ts="2026-03-11T09:20:00",
    trade_date="2026-03-11",
)

occ.C.INSTRUMENTS = {{"NIFTY": object()}}
occ.C.get_instrument = lambda inst: SimpleNamespace(
    api_code="NIFTY",
    exchange="NFO",
    strike_gap=50,
    min_strike=20000,
    max_strike=24000,
    lot_size=50,
)
occ.C.get_next_expiries = lambda inst, n: ["2026-03-26", "2026-04-02"]
occ.C.get_natural_expiry_for = lambda inst, expiry: expiry

spec = importlib.util.spec_from_file_location("app_main_test", r"/workspaces/breeze-pro-26-feb-2026/app.py")
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)


class FakeCacheManager:
    store = {{}}

    @classmethod
    def get(cls, key, kind):
        return cls.store.get((key, kind))

    @classmethod
    def set(cls, key, value, kind, ttl):
        cls.store[(key, kind)] = value

    @classmethod
    def invalidate(cls, key, kind):
        cls.store.pop((key, kind), None)


app_main._db = db
app_main.CacheManager = FakeCacheManager
app_main.get_client = lambda: object()
app_main.render_auto_refresh = lambda name: None
app_main.page_header = lambda title: st.title(title)
app_main.load_cached_option_chain = (
    lambda cache_manager, client, db, instrument, cfg, expiry, spinner: make_frame(expiry)
)
app_main.load_option_chain_spot = lambda cache_manager, client, cfg, session_state: 22020.0
app_main.SessionState.is_authenticated = staticmethod(lambda: True)
app_main.SessionState.log_activity = staticmethod(lambda *args, **kwargs: None)
app_main.sync_option_chain_live_feed = lambda *args, **kwargs: {{"NFO|NIFTY|options|2026-03-26|22000.0|call": "tok"}}
app_main.apply_option_chain_live_overlay = (
    lambda quote_mode, display_df, token_map, instrument, expiry: (
        display_df.assign(
            ltp=pd.to_numeric(display_df["ltp"], errors="coerce").fillna(0.0) + 9.0,
            quote_age_seconds=0.5,
        )
        if quote_mode == "🔴 Live WS"
        else display_df
    )
)
app_main.export_to_csv = lambda df, filename, label="": st.caption(f"Export ready: {{filename}}")

original_render_controls = app_main.render_option_chain_controls


def instrumented_render_controls(state, format_expiry, format_expiry_short):
    controls = original_render_controls(state, format_expiry, format_expiry_short)
    return replace(controls, show_greeks=False)


app_main.render_option_chain_controls = instrumented_render_controls

original_render_chart = app_main.render_option_chain_chart


def instrumented_render_chart(fig, chart_tab, selected_strike, all_strikes, atm):
    if fig is not None and getattr(fig.layout.title, "text", ""):
        st.caption(f"Chart title: {{fig.layout.title.text}}")
    return original_render_chart(fig, chart_tab, selected_strike, all_strikes, atm)


app_main.render_option_chain_chart = instrumented_render_chart
app_main.page_option_chain.__wrapped__.__wrapped__()
"""


def _build_app_test(tmp_path) -> AppTest:
    db_path = tmp_path / "option_chain_streamlit.db"
    front_fixture = "/workspaces/breeze-pro-26-feb-2026/tests/fixtures/option_chain_balanced.json"
    next_fixture = "/workspaces/breeze-pro-26-feb-2026/tests/fixtures/option_chain_expiry_day.json"
    at = AppTest.from_string(
        _streamlit_option_chain_script(
            str(db_path),
            front_fixture,
            next_fixture,
        )
    )
    at.default_timeout = 8
    return at


def _find_widget(collection, label: str):
    for widget in collection:
        if getattr(widget, "label", "") == label:
            return widget
    raise AssertionError(f"Widget not found: {label}")


def _captions(at: AppTest) -> list[str]:
    return [element.value for element in at.caption]


def _ladder_df(at: AppTest):
    assert at.dataframe
    return at.dataframe[0].value


def test_option_chain_page_streamlit_quote_modes_end_to_end(tmp_path):
    at = _build_app_test(tmp_path)
    at.run()

    assert [element.value for element in at.title] == ["📊 Option Chain"]
    assert not at.error
    assert not at.exception
    assert _find_widget(at.radio, "Quote Mode").value == "🔴 Live WS"
    assert "Chart title: OI Profile" in _captions(at)
    assert round(float(_ladder_df(at).iloc[0]["call_ltp"]), 2) == 130.0
    assert at.session_state["option_chain_workspace_state"]["replay_mode"] is False

    _find_widget(at.radio, "Quote Mode").set_value("📦 Snapshot").run()
    assert "Replay snapshot: 2026-03-11T09:20:00" not in _captions(at)
    assert round(float(_ladder_df(at).iloc[0]["call_ltp"]), 2) == 121.0
    assert at.session_state["option_chain_workspace_state"]["replay_mode"] is False

    _find_widget(at.radio, "Quote Mode").set_value("⏪ Replay").run()
    assert "Replay snapshot: 2026-03-11T09:20:00" in _captions(at)
    assert round(float(_ladder_df(at).iloc[0]["call_ltp"]), 2) == 126.0
    assert at.session_state["option_chain_workspace_state"]["replay_mode"] is True

    _find_widget(at.slider, "Replay Snapshot").set_value(0).run()
    assert "Replay snapshot: 2026-03-11T09:15:00" in _captions(at)
    assert round(float(_ladder_df(at).iloc[0]["call_ltp"]), 2) == 121.0

    _find_widget(at.radio, "Quote Mode").set_value("🔴 Live WS").run()
    assert round(float(_ladder_df(at).iloc[0]["call_ltp"]), 2) == 130.0
    assert at.session_state["option_chain_workspace_state"]["replay_mode"] is False


def test_option_chain_page_streamlit_compare_chart_and_export_controls(tmp_path):
    at = _build_app_test(tmp_path)
    at.run()

    _find_widget(at.multiselect, "Compare Expiries").set_value(["2026-04-02"]).run()
    _find_widget(at.sidebar.selectbox, "Compare Normalization").set_value("ATM %").run()
    _find_widget(at.sidebar.selectbox, "Chart Tab").set_value("Compare OI").run()

    captions = _captions(at)
    assert "Comparison mode: ATM %" in captions
    assert "Chart title: Multi-Expiry OI Overlay" in captions
    assert "Export ready: option_chain_NIFTY_2026-03-26.csv" in captions
    assert not at.error
    assert not at.exception

    _find_widget(at.sidebar.checkbox, "Export Button").set_value(False).run()
    assert "Export ready: option_chain_NIFTY_2026-03-26.csv" not in _captions(at)

    _find_widget(at.radio, "Quote Mode").set_value("⏪ Replay").run()
    _find_widget(at.sidebar.selectbox, "Chart Tab").set_value("Delta OI").run()
    captions = _captions(at)
    assert "Replay snapshot: 2026-03-11T09:20:00" in captions
    assert "Chart title: Replay Delta/OI Change (Since Open)" in captions
