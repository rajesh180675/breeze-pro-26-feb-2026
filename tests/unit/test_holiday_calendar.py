from datetime import date

import holiday_calendar


def test_is_holiday_returns_bool():
    result = holiday_calendar.is_holiday(date(2026, 1, 26))
    assert isinstance(result, bool)


def test_force_refresh_returns_tuple():
    count, ok = holiday_calendar.force_refresh()
    assert isinstance(count, int)
    assert isinstance(ok, bool)
