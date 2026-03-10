import threading
import time
from datetime import datetime

import risk_monitor as rm_mod
from risk_monitor import ExpiryDayAutopilot, RiskMonitor, SmartStopManager


class DummyClient:
    def __init__(self, ltp=100.0, fail=False):
        self.ltp = ltp
        self.fail = fail
        self.calls = 0

    def get_option_quote(self, *args, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("quote failed")
        return {"success": True, "data": {"Success": [{"ltp": self.ltp}]}}


def test_smart_stop_long_position_sets_stop_below_avg_price():
    p = rm_mod.MonitoredPosition("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "long", 75, 100.0, current_price=120.0)
    decision = SmartStopManager().evaluate([p], 50_000, 0)["p1"]
    assert decision["recommended_stop"] < p.avg_price


def test_smart_stop_short_position_sets_stop_above_avg_price():
    p = rm_mod.MonitoredPosition("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 100.0, current_price=90.0)
    decision = SmartStopManager().evaluate([p], 50_000, 0)["p1"]
    assert decision["recommended_stop"] > p.avg_price


def test_trailing_stop_locks_in_gain_as_price_moves():
    p = rm_mod.MonitoredPosition("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 100.0, current_price=80.0)
    stop = SmartStopManager().evaluate([p], 50_000, 0)["p1"]["recommended_stop"]
    assert stop < 200.0
    assert stop > p.current_price


def test_portfolio_stop_overrides_position_stop():
    p = rm_mod.MonitoredPosition("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 100.0, current_price=130.0)
    decision = SmartStopManager().evaluate([p], 1000.0, portfolio_pnl=-5000.0)["p1"]
    assert decision["auto_close"] is True
    assert "Portfolio" in decision["reason"]


def test_expiry_day_autopilot_recommends_close_on_expiry(monkeypatch):
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 26, 15, 20)

        @classmethod
        def strptime(cls, date_string, fmt):
            return datetime.strptime(date_string, fmt)

    monkeypatch.setattr(rm_mod, "datetime", FakeDateTime)
    p = rm_mod.MonitoredPosition("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 100.0)
    out = ExpiryDayAutopilot().evaluate([p], enabled=True)
    assert out["should_auto_close"] is True
    assert out["stage"] == "AUTO_CLOSE_WINDOW"


def test_expiry_day_autopilot_no_action_before_expiry(monkeypatch):
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 20, 14, 50)

        @classmethod
        def strptime(cls, date_string, fmt):
            return datetime.strptime(date_string, fmt)

    monkeypatch.setattr(rm_mod, "datetime", FakeDateTime)
    p = rm_mod.MonitoredPosition("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 100.0)
    out = ExpiryDayAutopilot().evaluate([p], enabled=True)
    assert out["should_auto_close"] is False
    assert out["stage"] == "IDLE"


def test_risk_monitor_start_stop_lifecycle():
    rm = RiskMonitor(DummyClient(), poll_interval=0.05)
    rm.start()
    assert rm._thread is not None and rm._thread.is_alive()
    rm.stop()
    deadline = time.time() + 2
    while rm._thread is not None and time.time() < deadline:
        time.sleep(0.01)
    assert rm._thread is None


def test_add_and_remove_position_thread_safe():
    rm = RiskMonitor(DummyClient(), poll_interval=0.05)

    def add(i):
        rm.add_position(f"p{i}", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 100.0)

    threads = [threading.Thread(target=add, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(rm.get_monitored_summary()) == 5


def test_get_smart_stop_summary_returns_all_fields():
    rm = RiskMonitor(DummyClient(), poll_interval=0.1)
    rm.add_position("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 50.0)
    rm._check_all()
    row = rm.get_smart_stop_summary()[0]
    for key in ["id", "stock", "strike", "type", "pos", "current", "recommended_stop"]:
        assert key in row


def test_risk_monitor_does_not_call_api_when_no_positions():
    client = DummyClient()
    rm = RiskMonitor(client, poll_interval=0.1)
    rm._check_all()
    assert client.calls == 0


def test_quote_failures_do_not_crash_check_all():
    rm = RiskMonitor(DummyClient(fail=True), poll_interval=0.01)
    rm.add_position("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 100.0)
    rm._check_all()
    assert rm.get_monitored_summary()[0]["id"] == "p1"


def test_loop_clears_running_on_unhandled_exception(monkeypatch):
    rm = RiskMonitor(DummyClient(), poll_interval=0)
    rm._running.set()

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(rm, "_check_all", boom)
    rm._loop()
    assert rm.is_running() is False
