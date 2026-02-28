"""Tests for parse_period() — all 5 formats, future-date rejection, invalid inputs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from status_report.config import ReportPeriod, parse_period


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utc_today_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _utc_yesterday_start() -> datetime:
    return _utc_today_start() - timedelta(days=1)


def _utc_yesterday_end() -> datetime:
    return _utc_yesterday_start().replace(hour=23, minute=59, second=59, microsecond=999999)


# ── "today" ───────────────────────────────────────────────────────────────────


class TestParsePeriodToday:
    def test_start_is_midnight_utc(self):
        period = parse_period("today")
        expected_start = _utc_today_start()
        assert period.start == expected_start

    def test_end_is_at_or_before_now(self):
        before = datetime.now(UTC)
        period = parse_period("today")
        after = datetime.now(UTC)
        assert before <= period.end <= after

    def test_label_is_today(self):
        assert parse_period("today").label == "today"

    def test_start_before_end(self):
        period = parse_period("today")
        assert period.start <= period.end


# ── "yesterday" ───────────────────────────────────────────────────────────────


class TestParsePeriodYesterday:
    def test_start_is_yesterday_midnight_utc(self):
        period = parse_period("yesterday")
        assert period.start == _utc_yesterday_start()

    def test_end_is_yesterday_end_of_day(self):
        period = parse_period("yesterday")
        assert period.end == _utc_yesterday_end()

    def test_label_is_yesterday(self):
        assert parse_period("yesterday").label == "yesterday"

    def test_start_hour_is_zero(self):
        period = parse_period("yesterday")
        assert period.start.hour == 0
        assert period.start.minute == 0
        assert period.start.second == 0

    def test_end_hour_is_23(self):
        period = parse_period("yesterday")
        assert period.end.hour == 23
        assert period.end.minute == 59
        assert period.end.second == 59

    def test_end_is_in_past(self):
        period = parse_period("yesterday")
        assert period.end < datetime.now(UTC)


# ── "last-24h" ────────────────────────────────────────────────────────────────


class TestParsePeriodLast24h:
    def test_window_is_approximately_24_hours(self):
        period = parse_period("last-24h")
        delta = period.end - period.start
        # Allow ±2s for test execution time
        assert abs(delta.total_seconds() - 86400) < 2

    def test_end_is_close_to_now(self):
        before = datetime.now(UTC)
        period = parse_period("last-24h")
        after = datetime.now(UTC)
        assert before <= period.end <= after

    def test_label_is_last_24h(self):
        assert parse_period("last-24h").label == "last-24h"

    def test_start_is_utc_aware(self):
        period = parse_period("last-24h")
        assert period.start.tzinfo is not None
        assert period.end.tzinfo is not None


# ── YYYY-MM-DD (specific date) ────────────────────────────────────────────────


class TestParsePeriodSpecificDate:
    def test_start_is_midnight_utc(self):
        period = parse_period("2026-01-15")
        assert period.start == datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC)

    def test_end_is_end_of_day_utc(self):
        period = parse_period("2026-01-15")
        assert period.end == datetime(2026, 1, 15, 23, 59, 59, 999999, tzinfo=UTC)

    def test_label_is_none(self):
        assert parse_period("2026-01-15").label is None

    def test_start_and_end_are_same_calendar_date(self):
        period = parse_period("2026-01-15")
        assert period.start.date() == period.end.date()

    @pytest.mark.parametrize("date_str", [
        "2026-01-01",
        "2025-12-31",
        "2024-02-29",  # leap year
        "2026-02-01",
    ])
    def test_parametrized_past_dates_accepted(self, date_str: str):
        period = parse_period(date_str)
        assert period.start.tzinfo == UTC
        assert period.end.tzinfo == UTC
        assert period.start < period.end

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            parse_period("2026-13-01")  # invalid month

    def test_invalid_day_raises(self):
        with pytest.raises(ValueError):
            parse_period("2026-02-30")  # Feb 30 doesn't exist


# ── YYYY-MM-DD:YYYY-MM-DD (date range) ────────────────────────────────────────


class TestParsePeriodDateRange:
    def test_start_is_midnight_of_first_date(self):
        period = parse_period("2026-01-10:2026-01-15")
        assert period.start == datetime(2026, 1, 10, 0, 0, 0, tzinfo=UTC)

    def test_end_is_end_of_last_date(self):
        period = parse_period("2026-01-10:2026-01-15")
        assert period.end == datetime(2026, 1, 15, 23, 59, 59, 999999, tzinfo=UTC)

    def test_label_is_none(self):
        assert parse_period("2026-01-10:2026-01-15").label is None

    def test_single_day_range(self):
        period = parse_period("2026-01-15:2026-01-15")
        assert period.start.date() == period.end.date()

    def test_week_range(self):
        period = parse_period("2026-02-01:2026-02-07")
        delta_days = (period.end - period.start).days
        assert delta_days == 6  # 7 days inclusive → 6 day delta at start of first

    def test_invalid_start_date_raises(self):
        with pytest.raises(ValueError):
            parse_period("2026-13-01:2026-01-15")

    def test_start_greater_than_end_raises(self):
        """start > end in a date range raises ValueError from ReportPeriod.__post_init__."""
        with pytest.raises(ValueError):
            parse_period("2026-01-15:2026-01-10")


# ── Future date rejection (FR-014) ────────────────────────────────────────────


class TestParsePeriodFutureDateRejection:
    def test_future_specific_date_raises(self):
        with pytest.raises(ValueError, match="future date"):
            parse_period("2099-01-01")

    def test_future_range_raises(self):
        with pytest.raises(ValueError, match="future date"):
            parse_period("2026-02-01:2099-12-31")

    def test_today_does_not_raise(self):
        # "today" end = now() which is not future
        period = parse_period("today")
        assert period is not None

    def test_last_24h_does_not_raise(self):
        period = parse_period("last-24h")
        assert period is not None

    def test_yesterday_does_not_raise(self):
        period = parse_period("yesterday")
        assert period is not None


# ── Unrecognised formats ──────────────────────────────────────────────────────


class TestParsePeriodInvalidFormats:
    @pytest.mark.parametrize("bad_value", [
        "tomorrow",
        "last-week",
        "2026/01/15",        # wrong separator
        "01-15-2026",        # wrong order
        "2026-1-5",          # no zero-padding
        "",                  # empty string
        "2026-01",           # missing day
        "2026-01-15T00:00",  # datetime string (not supported format)
    ])
    def test_unrecognised_format_raises_value_error(self, bad_value: str):
        with pytest.raises(ValueError):
            parse_period(bad_value)


# ── ReportPeriod dataclass ────────────────────────────────────────────────────


class TestReportPeriod:
    def test_start_equals_end_is_valid(self):
        now = datetime.now(UTC)
        period = ReportPeriod(label=None, start=now, end=now)
        assert period.start == period.end

    def test_start_after_end_raises(self):
        now = datetime.now(UTC)
        past = now - timedelta(hours=1)
        with pytest.raises(ValueError):
            ReportPeriod(label=None, start=now, end=past)

    def test_label_can_be_none(self):
        now = datetime.now(UTC)
        period = ReportPeriod(label=None, start=now, end=now)
        assert period.label is None

    def test_label_can_be_string(self):
        now = datetime.now(UTC)
        period = ReportPeriod(label="custom", start=now, end=now)
        assert period.label == "custom"
