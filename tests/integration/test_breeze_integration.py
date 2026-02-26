import os

import pytest

from lib.breeze_client import BreezeClient


@pytest.mark.integration
def test_positions_integration():
    if not all(
        [
            os.getenv("BREEZE_CLIENT_ID"),
            os.getenv("BREEZE_CLIENT_SECRET"),
            os.getenv("BREEZE_SESSION_TOKEN"),
        ]
    ):
        pytest.skip("Breeze integration credentials missing; skipping integration suite.")

    client = BreezeClient()
    result = client.get_positions()
    assert isinstance(result, dict)
