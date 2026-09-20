import datetime as dt

import pytest

from app.services.walk_forward_service import _generate_windows


def test_sequential_non_overlapping_windows():
    windows = _generate_windows(dt.date(2026, 1, 1), dt.date(2026, 4, 1), window_days=30, step_days=30)
    assert windows == [
        (dt.date(2026, 1, 1), dt.date(2026, 1, 31)),
        (dt.date(2026, 1, 31), dt.date(2026, 3, 2)),
        (dt.date(2026, 3, 2), dt.date(2026, 4, 1)),
    ]


def test_rolling_overlapping_windows():
    windows = _generate_windows(dt.date(2026, 1, 1), dt.date(2026, 2, 1), window_days=20, step_days=10)
    assert windows == [
        (dt.date(2026, 1, 1), dt.date(2026, 1, 21)),
        (dt.date(2026, 1, 11), dt.date(2026, 1, 31)),
    ]


def test_no_windows_fit_returns_empty_list():
    windows = _generate_windows(dt.date(2026, 1, 1), dt.date(2026, 1, 10), window_days=30, step_days=30)
    assert windows == []


def test_rejects_end_before_start():
    with pytest.raises(ValueError):
        _generate_windows(dt.date(2026, 2, 1), dt.date(2026, 1, 1), window_days=30, step_days=30)


def test_rejects_non_positive_window_or_step():
    with pytest.raises(ValueError):
        _generate_windows(dt.date(2026, 1, 1), dt.date(2026, 2, 1), window_days=0, step_days=30)
    with pytest.raises(ValueError):
        _generate_windows(dt.date(2026, 1, 1), dt.date(2026, 2, 1), window_days=30, step_days=-5)
