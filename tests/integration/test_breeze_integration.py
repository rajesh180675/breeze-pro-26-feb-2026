import os

import pytest

from lib.breeze_client import BreezeClient


def _require_breeze_credentials() -> None:
    if all(
        [
            os.getenv("BREEZE_CLIENT_ID"),
            os.getenv("BREEZE_CLIENT_SECRET"),
            os.getenv("BREEZE_SESSION_TOKEN"),
        ]
    ):
        return
    pytest.skip("Breeze integration credentials missing; skipping integration suite.")


def _assert_nonempty_json_object(result: dict) -> None:
    assert isinstance(result, dict)
    assert result
    assert all(isinstance(key, str) for key in result)


@pytest.mark.integration
def test_customer_details_integration() -> None:
    _require_breeze_credentials()
    client = BreezeClient()
    result = client.get_customer_details()
    _assert_nonempty_json_object(result)


@pytest.mark.integration
def test_positions_integration() -> None:
    _require_breeze_credentials()
    client = BreezeClient()
    result = client.get_positions()
    _assert_nonempty_json_object(result)
