import os

import pytest

from app.lib.breeze_client import BreezeClient

_REQUIRED_ENV_VARS = (
    "BREEZE_CLIENT_ID",
    "BREEZE_CLIENT_SECRET",
    "BREEZE_SESSION_TOKEN",
)


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _missing_required_env_vars() -> list[str]:
    return [name for name in _REQUIRED_ENV_VARS if not os.getenv(name)]


_MISSING_ENV_VARS = _missing_required_env_vars()
_MISSING_MESSAGE = f"Breeze integration credentials missing: {', '.join(_MISSING_ENV_VARS)}"

if _MISSING_ENV_VARS and _is_truthy(os.getenv("BREEZE_INTEGRATION_STRICT")):
    raise RuntimeError(_MISSING_MESSAGE)

if _MISSING_ENV_VARS:
    pytestmark = pytest.mark.skip(reason=f"{_MISSING_MESSAGE}; skipping integration suite.")


def _assert_nonempty_json_object(result: dict) -> None:
    assert isinstance(result, dict)
    assert result
    assert all(isinstance(key, str) for key in result)


@pytest.mark.integration
def test_customer_details_integration() -> None:
    client = BreezeClient()
    result = client.get_customer_details()
    _assert_nonempty_json_object(result)


@pytest.mark.integration
def test_positions_integration() -> None:
    client = BreezeClient()
    result = client.get_positions()
    _assert_nonempty_json_object(result)
