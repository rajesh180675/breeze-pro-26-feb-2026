"""Compatibility shim for Breeze websocket client."""

from app.infrastructure.breeze import websocket_client as _websocket_client

BreezeWebsocketClient = _websocket_client.BreezeWebsocketClient
time = _websocket_client.time

__all__ = ["BreezeWebsocketClient"]
