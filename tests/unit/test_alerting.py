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


def test_dispatch_is_async_and_deduplicates_within_60s(monkeypatch):
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

    d.dispatch(event)
    time.sleep(0.02)
    assert tg.calls == first_calls


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
