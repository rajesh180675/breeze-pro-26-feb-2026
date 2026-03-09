import os
import pytest

from breeze_api import BreezeAPIClient
import live_feed as lf

pytestmark = pytest.mark.integration


def _client():
    required = ["BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing integration credentials: {', '.join(missing)}")
    c = BreezeAPIClient(os.environ["BREEZE_API_KEY"], os.environ["BREEZE_API_SECRET"])
    assert c.connect(os.environ["BREEZE_SESSION_TOKEN"]).get("success")
    return c


def test_ws_manager_init_and_health():
    client = _client()
    mgr = lf.initialize_live_feed(client.breeze)
    stats = mgr.get_health_stats()
    assert "total_subscriptions" in stats
