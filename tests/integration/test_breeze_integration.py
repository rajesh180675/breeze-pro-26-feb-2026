import os

import pytest

from lib.breeze_client import BreezeClient


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_breeze_credentials() -> None:
    required_vars = [
        "BREEZE_CLIENT_ID",
        "BREEZE_CLIENT_SECRET",
        "BREEZE_SESSION_TOKEN",
    ]
    missing_vars = [name for name in required_vars if not os.getenv(name)]
    if not missing_vars:
        return
    message = f"Breeze integration credentials missing: {', '.join(missing_vars)}"
    if _is_truthy(os.getenv("BREEZE_INTEGRATION_STRICT")):
        pytest.fail(message)
    pytest.skip(f"{message}; skipping integration suite.")


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
