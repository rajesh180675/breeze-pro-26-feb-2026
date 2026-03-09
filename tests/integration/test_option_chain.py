import os
import pytest

import app_config as C
from breeze_api import BreezeAPIClient

pytestmark = pytest.mark.integration


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
