import os
import pytest

from breeze_api import BreezeAPIClient

pytestmark = pytest.mark.integration


def _require_creds():
    required = ["BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing integration credentials: {', '.join(missing)}")


def test_auth_flow_live_session():
    _require_creds()
    client = BreezeAPIClient(os.environ["BREEZE_API_KEY"], os.environ["BREEZE_API_SECRET"])
    resp = client.connect(os.environ["BREEZE_SESSION_TOKEN"])
    assert resp.get("success") is True
