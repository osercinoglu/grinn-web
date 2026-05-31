"""Unit tests for the reconciler's calc.log parsing helpers."""

from pathlib import Path

import pytest

from shared.reconciler import _calc_log_ends_with_success, _read_elapsed_seconds


FIXTURES = Path(__file__).parent / "fixtures"
COMPLETED = FIXTURES / "calc_log_completed.log"
FAILED_MIDRUN = FIXTURES / "calc_log_failed_midrun.log"
TRUNCATED = FIXTURES / "calc_log_truncated.log"
EMPTY = FIXTURES / "calc_log_empty.log"
MISSING = FIXTURES / "this_does_not_exist.log"


class TestCalcLogEndsWithSuccess:
    def test_returns_true_for_completed_log(self):
        assert _calc_log_ends_with_success(COMPLETED) is True

    def test_returns_false_for_failed_midrun_log(self):
        assert _calc_log_ends_with_success(FAILED_MIDRUN) is False

    def test_returns_false_for_truncated_log(self):
        assert _calc_log_ends_with_success(TRUNCATED) is False

    def test_returns_false_for_empty_log(self):
        assert _calc_log_ends_with_success(EMPTY) is False

    def test_returns_false_for_missing_file(self):
        assert _calc_log_ends_with_success(MISSING) is False


class TestReadElapsedSeconds:
    def test_returns_float_for_completed_log(self):
        elapsed = _read_elapsed_seconds(COMPLETED)
        assert elapsed == pytest.approx(5557.14)

    def test_returns_none_for_failed_midrun_log(self):
        assert _read_elapsed_seconds(FAILED_MIDRUN) is None

    def test_returns_none_for_truncated_log(self):
        assert _read_elapsed_seconds(TRUNCATED) is None

    def test_returns_none_for_empty_log(self):
        assert _read_elapsed_seconds(EMPTY) is None

    def test_returns_none_for_missing_file(self):
        assert _read_elapsed_seconds(MISSING) is None
