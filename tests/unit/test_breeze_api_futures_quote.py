import sys
import types
from unittest.mock import Mock

fake_mod = types.ModuleType("breeze_connect")
fake_mod.BreezeConnect = object
sys.modules.setdefault("breeze_connect", fake_mod)

from breeze_api import BreezeAPIClient


def test_get_futures_quote_rejects_invalid_exchange():
    client = BreezeAPIClient("k", "s")
    client.connected = True
    client.breeze = Mock()

    resp = client.get_futures_quote("NIFTY", "NSE", "2026-03-26")

    assert resp["success"] is False
    assert "Allowed: NFO, BFO" in resp["message"]
