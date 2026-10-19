from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from mimic42.core.admin import statistics_window


@pytest.mark.parametrize("days", [7, 30])
def test_statistics_window_uses_utc_calendar_days_and_exclusive_now(days: int) -> None:
    now = datetime(2026, 10, 18, 12, 34, 56, 789, tzinfo=UTC)

    since, until = statistics_window(days, now)

    assert since == datetime(2026, 10, 18, tzinfo=UTC) - timedelta(days=days - 1)
    assert until == now


def test_statistics_window_normalizes_non_utc_datetime_before_truncating_day() -> None:
    now = datetime(2026, 10, 18, 18, 0, tzinfo=timezone(timedelta(hours=6)))

    since, until = statistics_window(7, now)

    assert since == datetime(2026, 10, 12, tzinfo=UTC)
    assert until == datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("days", [1, 14, 31])
def test_statistics_window_rejects_unsupported_period(days: int) -> None:
    with pytest.raises(ValueError, match="7 или 30"):
        statistics_window(days, datetime(2026, 10, 18, tzinfo=UTC))  # type: ignore[arg-type]


def test_statistics_window_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="часовым поясом"):
        statistics_window(7, datetime(2026, 10, 18))
