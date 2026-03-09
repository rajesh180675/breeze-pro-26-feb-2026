import os
import pytest

from paper_trading import PaperTradingEngine
from breeze_api import BreezeAPIClient

pytestmark = pytest.mark.integration


class _DummyTickStore:
    def get_latest_ltp(self, _token):
        return None


def _client():
    required = ["BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing integration credentials: {', '.join(missing)}")
    c = BreezeAPIClient(os.environ["BREEZE_API_KEY"], os.environ["BREEZE_API_SECRET"])
    assert c.connect(os.environ["BREEZE_SESSION_TOKEN"]).get("success")
    return c


def test_paper_order_lifecycle_smoke():
    client = _client()
    engine = PaperTradingEngine(client, _DummyTickStore())
    # Only validate that paper path is callable in integration environment.
    assert hasattr(engine, "place_order")
