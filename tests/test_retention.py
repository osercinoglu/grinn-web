"""Unit tests for shared.retention — job-file deletion countdown helpers.

The deletion deadline is created_at + JOB_FILE_RETENTION_HOURS (measured from
job submission, not completion — see shared/local_storage.py cleanup_old_jobs).
These pure helpers are kept Dash-free so they can be tested without importing
the frontend app.
"""

from datetime import datetime, timedelta, timezone

import pytest

from shared.retention import (
    file_expiry,
    remaining_until_deletion,
    format_remaining,
    format_retention,
)


UTC = timezone.utc


class TestFileExpiry:
    def test_adds_retention_hours_to_aware_created_at(self):
        created = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        assert file_expiry(created, 72) == datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    def test_treats_naive_created_at_as_utc(self):
        created = datetime(2026, 5, 1, 12, 0)  # naive — must be assumed UTC
        assert file_expiry(created, 72) == datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    def test_supports_fractional_hours(self):
        created = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        assert file_expiry(created, 1.5) == datetime(2026, 5, 1, 1, 30, tzinfo=UTC)


class TestRemainingUntilDeletion:
    def test_positive_before_expiry(self):
        created = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        assert remaining_until_deletion(created, 72, now=now) == timedelta(hours=60)

    def test_negative_past_expiry(self):
        created = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        now = datetime(2026, 5, 5, 0, 0, tzinfo=UTC)  # 96h later, retention 72h
        assert remaining_until_deletion(created, 72, now=now) == timedelta(hours=-24)

    def test_naive_now_treated_as_utc(self):
        created = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        now = datetime(2026, 5, 1, 0, 0)  # naive
        assert remaining_until_deletion(created, 72, now=now) == timedelta(hours=72)


class TestFormatRemaining:
    def test_days_and_hours(self):
        assert format_remaining(timedelta(days=2, hours=4, minutes=11)) == "2d 4h"

    def test_whole_days_only(self):
        assert format_remaining(timedelta(days=3)) == "3d"

    def test_hours_and_minutes(self):
        assert format_remaining(timedelta(hours=5, minutes=12)) == "5h 12m"

    def test_whole_hours_only(self):
        assert format_remaining(timedelta(hours=5)) == "5h"

    def test_minutes_only(self):
        assert format_remaining(timedelta(minutes=8)) == "8m"

    def test_under_a_minute(self):
        assert format_remaining(timedelta(seconds=30)) == "less than a minute"

    def test_zero_is_imminently(self):
        assert format_remaining(timedelta(0)) == "imminently"

    def test_negative_is_imminently(self):
        assert format_remaining(timedelta(hours=-3)) == "imminently"


class TestFormatRetention:
    def test_default_72_hours(self):
        assert format_retention(72) == "72 hours (3 days)"

    def test_float_input_is_clean(self):
        assert format_retention(72.0) == "72 hours (3 days)"

    def test_one_day(self):
        assert format_retention(24) == "24 hours (1 day)"

    def test_fractional_days(self):
        assert format_retention(36) == "36 hours (1.5 days)"

    def test_sub_day_hours_only(self):
        assert format_retention(12) == "12 hours"

    def test_single_hour(self):
        assert format_retention(1) == "1 hour"
