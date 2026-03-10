from datetime import date, timedelta

import pytest

from validators import validate_date_range


def test_validate_date_range_rejects_more_than_365_days():
    start = date(2025, 1, 1)
    end = start + timedelta(days=400)

    with pytest.raises(ValueError, match="maximum of 365 days"):
        validate_date_range(start, end)


def test_validate_date_range_accepts_365_days_boundary():
    start = date(2025, 1, 1)
    end = start + timedelta(days=365)

    assert validate_date_range(start, end) is True


def test_validate_date_range_rejects_inverted_range():
    start = date(2025, 2, 1)
    end = date(2025, 1, 1)

    with pytest.raises(ValueError, match="cannot be after To date"):
        validate_date_range(start, end)
