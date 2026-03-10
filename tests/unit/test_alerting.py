import hashlib
import hmac
import json
import time

from alerting import AlertConfig, AlertDispatcher, AlertEvent, AlertLevel, WebhookDispatcher


class _DummyDispatcher:
    def __init__(self):
        self.calls = 0

    def format_alert(self, event):
        return event.title

    def send(self, *_args, **_kwargs):
        self.calls += 1
        return True


def test_webhook_signature_matches_hmac_sha256():
    wh = WebhookDispatcher(url="https://example.com/hook", secret="secret")
    event = AlertEvent(alert_type="A", level=AlertLevel.INFO, title="T", body="B")
    payload = wh.build_payload(event)

    got = wh.signature_for_payload(payload)
    expected = hmac.new(
        b"secret",
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert got == expected


def test_dispatch_is_async_and_deduplicates_within_5m(monkeypatch):
    d = AlertDispatcher(AlertConfig())
    tg = _DummyDispatcher()
    d._telegram = tg
    d._email = None
    d._webhook = None

    event = AlertEvent(alert_type="TRADE_FILLED", level=AlertLevel.INFO, title="Fill", body="Filled")

    start = time.perf_counter()
    d.dispatch(event)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.001

    time.sleep(0.02)
    first_calls = tg.calls
    assert first_calls == 1
    hist = d.get_history(limit=1)
    assert hist
    assert "channels" in hist[0]

    d.dispatch(event)
    time.sleep(0.02)
    assert tg.calls == first_calls


def test_webhook_verify_signature():
    wh = WebhookDispatcher(url="https://example.com/hook", secret="secret")
    raw = '{"a":1}'
    sig = hmac.new(b"secret", raw.encode(), hashlib.sha256).hexdigest()
    assert wh.verify_signature(raw, sig) is True
    assert wh.verify_signature(raw, "bad-signature") is False


def test_webhook_payload_contains_all_event_fields():
    event = AlertEvent(
        alert_type="MARGIN_CALL",
        level=AlertLevel.CRITICAL,
        title="Low Margin",
        body="Margin warning",
        metadata={"x": 1},
    )
    wh = WebhookDispatcher(url="https://example.com")
    payload = wh.build_payload(event)

    assert set(["alert_type", "level", "title", "body", "metadata", "timestamp"]).issubset(payload.keys())
    assert payload["alert_type"] == "MARGIN_CALL"
    assert payload["level"] == "CRITICAL"


class _SequencedDispatcher:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def send(self, *_args, **_kwargs):
        self.calls += 1
        idx = self.calls - 1
        return self.results[idx] if idx < len(self.results) else self.results[-1]


def _base_event(title="Test Alert"):
    return AlertEvent(alert_type="TRADE_FILLED", level=AlertLevel.INFO, title=title, body="Body")


def test_send_with_retry_success_on_first_attempt(monkeypatch):
    d = AlertDispatcher(AlertConfig())
    monkeypatch.setattr("alerting.time.sleep", lambda *_args, **_kwargs: None)
    tg = _SequencedDispatcher([True])
    d._telegram = tg
    d._email = None
    d._webhook = None
    d._discord = None
    d._whatsapp = None

    d._send_all(_base_event("First attempt"))

    assert tg.calls == 1
    assert d.get_history(limit=1)[0]["channels"] == "telegram"


def test_send_with_retry_fails_then_succeeds(monkeypatch):
    d = AlertDispatcher(AlertConfig())
    monkeypatch.setattr("alerting.time.sleep", lambda *_args, **_kwargs: None)
    tg = _SequencedDispatcher([False, True])
    d._telegram = tg
    d._email = None
    d._webhook = None
    d._discord = None
    d._whatsapp = None

    d._send_all(_base_event("Retry success"))

    assert tg.calls == 2
    assert d.get_history(limit=1)[0]["channels"] == "telegram"


def test_send_with_retry_fails_both_attempts(monkeypatch, caplog):
    d = AlertDispatcher(AlertConfig())
    monkeypatch.setattr("alerting.time.sleep", lambda *_args, **_kwargs: None)
    tg = _SequencedDispatcher([False, False])
    d._telegram = tg
    d._email = None
    d._webhook = None
    d._discord = None
    d._whatsapp = None

    d._send_all(_base_event("Retry fail"))

    assert tg.calls == 2
    assert d.get_history(limit=1)[0]["channels"] == "none"
    assert "channel=telegram title=Retry fail" in caplog.text


def test_history_is_capped_and_pruned(monkeypatch):
    d = AlertDispatcher(AlertConfig())
    monkeypatch.setattr("alerting.time.sleep", lambda *_args, **_kwargs: None)
    tg = _SequencedDispatcher([True])
    d._telegram = tg
    d._email = None
    d._webhook = None
    d._discord = None
    d._whatsapp = None

    total_events = d.MAX_HISTORY + 5
    for i in range(total_events):
        d._send_all(_base_event(f"Event {i}"))

    history = d.get_history(limit=total_events)
    assert len(history) == d.MAX_HISTORY
    assert history[0]["title"] == f"Event {total_events - 1}"
    assert history[-1]["title"] == "Event 5"


def test_flush_drains_queue(monkeypatch):
    d = AlertDispatcher(AlertConfig())
    monkeypatch.setattr("alerting.time.sleep", lambda *_args, **_kwargs: None)
    d._stop.set()
    d.dispatch(_base_event("queued"))
    assert d.flush(timeout=0.2) is True
