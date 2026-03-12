"""Breeze WebSocket manager with reconnect and subscription tracking."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from breeze_connect import BreezeConnect

from app.lib.config import get_settings
from app.lib.errors import RateLimitError

LOGGER = logging.getLogger(__name__)


class BreezeWebsocketClient:
    """Durable websocket wrapper for Breeze feed subscriptions."""

    def __init__(self, sdk_client: BreezeConnect, max_subscriptions: int | None = None) -> None:
        self.settings = get_settings()
        self.sdk_client = sdk_client
        self.max_subscriptions = max_subscriptions or self.settings.websocket_max_subscriptions
        self._subscriptions: set[str] = set()
        self._callback: Callable[[dict], None] | None = None
        self._connected = False
        self._stop = threading.Event()

    def connect(self) -> None:
        """Connect websocket feed and start background reconnect loop."""
        self._stop.clear()
        self._connect_once()

    def _connect_once(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self.sdk_client.ws_connect()
                self._connected = True
                LOGGER.info("websocket_connected")
                return
            except Exception:  # noqa: BLE001
                backoff = min(30, 2**attempt)
                LOGGER.warning("websocket_connect_failed", extra={"duration_ms": backoff * 1000})
                time.sleep(backoff)
                attempt += 1

    def subscribe(self, instruments: list[str], callback: Callable[[dict], None]) -> None:
        """Subscribe to feed symbols with cap validation and callback dispatch."""
        new_symbols = [symbol for symbol in instruments if symbol not in self._subscriptions]
        if len(self._subscriptions) + len(new_symbols) > self.max_subscriptions:
            raise RateLimitError(
                "Subscription cap exceeded",
                operation="subscribe",
                http_status=429,
            )
        self._callback = callback
        for symbol in new_symbols:
            self.sdk_client.subscribe_feeds(stock_token=symbol)
            self._subscriptions.add(symbol)

    def handle_message(self, message: dict) -> None:
        """Forward incoming message to user callback."""
        if self._callback:
            self._callback(message)

    def disconnect(self) -> None:
        """Disconnect websocket gracefully."""
        self._stop.set()
        if self._connected:
            self.sdk_client.ws_disconnect()
            self._connected = False
        LOGGER.info("websocket_disconnected")
