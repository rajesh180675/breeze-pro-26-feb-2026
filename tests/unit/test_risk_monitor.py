from risk_monitor import RiskMonitor


class DummyClient:
    def get_option_quote(self, *args, **kwargs):
        return {"success": True, "data": {"Success": [{"ltp": 100}]}}


def test_smart_stop_summary_available():
    rm = RiskMonitor(DummyClient(), poll_interval=0.1)
    rm.add_position("p1", "NIFTY", "NFO", "2026-03-26", 22000, "CE", "short", 75, 50.0)
    rm._check_all()
    rows = rm.get_smart_stop_summary()
    assert rows
    assert rows[0]["id"] == "p1"


def test_loop_clears_running_on_unhandled_exception(monkeypatch):
    rm = RiskMonitor(DummyClient(), poll_interval=0)
    rm._running.set()

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(rm, "_check_all", boom)
    rm._loop()
    assert rm.is_running() is False
