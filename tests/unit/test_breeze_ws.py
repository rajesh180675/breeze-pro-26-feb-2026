from unittest.mock import Mock

import pytest

from lib.breeze_ws import BreezeWebsocketClient
from lib.errors import RateLimitError


def test_connect_retries_once_then_marks_connected(monkeypatch):
    client = Mock()
    client.ws_connect.side_effect = [RuntimeError("down"), None]
    sleeps: list[int] = []
    monkeypatch.setattr("lib.breeze_ws.time.sleep", lambda secs: sleeps.append(secs))

    ws = BreezeWebsocketClient(client, max_subscriptions=3)
    ws.connect()

    assert client.ws_connect.call_count == 2
    assert sleeps == [1]
    assert ws._connected is True


def test_subscribe_enforces_cap_and_records_tokens():
    client = Mock()
    ws = BreezeWebsocketClient(client, max_subscriptions=2)

    got: list[dict] = []
    ws.subscribe(["NSE:ABC"], got.append)
    ws.subscribe(["NSE:XYZ"], got.append)
    with pytest.raises(RateLimitError):
        ws.subscribe(["NSE:OVER"], got.append)

    assert ws._subscriptions == {"NSE:ABC", "NSE:XYZ"}
    assert client.subscribe_feeds.call_count == 2


def test_handle_message_forwards_to_callback():
    client = Mock()
    ws = BreezeWebsocketClient(client, max_subscriptions=2)
    received: list[dict] = []

    ws.subscribe(["NSE:ABC"], received.append)
    ws.handle_message({"price": 123})

    assert received == [{"price": 123}]


def test_disconnect_only_disconnects_when_connected():
    client = Mock()
    ws = BreezeWebsocketClient(client, max_subscriptions=2)

    ws.disconnect()
    client.ws_disconnect.assert_not_called()

    ws._connected = True
    ws.disconnect()
    client.ws_disconnect.assert_called_once()
    assert ws._connected is False
