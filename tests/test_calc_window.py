"""The best drying window, and the overnight dew check."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.laundry_weather import calc

from .conftest import TEST_TZ


def at(day: int, h: int) -> datetime:
    return datetime(2026, 8, day, h, 0, tzinfo=TEST_TZ)


def series(start: datetime, suns: list[float], temps: list[float] | None = None):
    return [
        calc.ScoredHour(
            ts=start + timedelta(hours=i),
            hhmm=(start + timedelta(hours=i)).strftime("%H:%M"),
            sun=sun,
            cov=sun * 0.4,
            wet=False,
            vpd=sun,
            temp_c=(temps[i] if temps else 18.0),
        )
        for i, sun in enumerate(suns)
    ]


def test_window_expands_around_the_peak() -> None:
    # 09:00 onwards. Peak 16.2 at 12:00, so the threshold is 9.72:
    # 11:00 (10.0) and 13:00 (12.0) clear it, 10:00 (6.0) and 14:00 (7.0) do not.
    day = series(at(22, 9), [2.0, 6.0, 10.0, 16.2, 12.0, 7.0, 2.0])
    window = calc.best_window(day)
    assert window is not None
    assert window.peak == pytest.approx(16.2)
    assert window.start == at(22, 11)
    assert window.end == at(22, 13)


def test_window_stops_at_a_dip_rather_than_jumping_it() -> None:
    """A good afternoon and a good tomorrow are two windows, not one."""
    day = series(at(22, 9), [12.0, 1.0, 20.0, 18.0, 1.0, 15.0])
    window = calc.best_window(day)
    assert window is not None
    assert window.start == at(22, 11)
    assert window.end == at(22, 12)


def test_an_isolated_peak_is_a_one_hour_window() -> None:
    day = series(at(22, 9), [1.0, 1.0, 20.0, 1.0])
    window = calc.best_window(day)
    assert window is not None
    assert window.start == window.end == at(22, 11)


def test_no_window_when_nothing_dries() -> None:
    assert calc.best_window(series(at(22, 9), [0.0, 0.0, 0.0])) is None


def test_no_window_without_a_forecast() -> None:
    assert calc.best_window([]) is None


def test_window_format_leads_with_the_weekday() -> None:
    """With a 48-hour horizon the best window is regularly tomorrow."""
    window = calc.Window(start=at(23, 11), end=at(23, 16), peak=16.2)
    assert calc.format_window(window) == "Sun 11:00-16:00 (peak 16.2)"


def test_window_spanning_midnight_names_both_days() -> None:
    window = calc.Window(start=at(22, 22), end=at(23, 2), peak=5.0)
    assert calc.format_window(window) == "Sat 22:00-Sun 02:00 (peak 5.0)"


def test_no_window_formats_as_nothing() -> None:
    assert calc.format_window(None) is None


# --- overnight dew ---------------------------------------------------------


def test_dew_flags_when_the_night_drops_below_the_dew_point() -> None:
    night = series(
        at(22, 17),
        [1.0] * 12,
        temps=[14, 12, 11, 10, 9, 8.4, 8.6, 9, 10, 12, 14, 16],
    )
    flagged, lowest = calc.overnight_rewet(night, at(22, 16), dewpoint_now=9.8)
    assert flagged is True
    assert lowest == pytest.approx(8.4)


def test_no_dew_when_the_night_stays_above_the_dew_point() -> None:
    night = series(at(22, 17), [1.0] * 8, temps=[18, 17, 16, 15, 15, 14, 14, 15])
    flagged, lowest = calc.overnight_rewet(night, at(22, 16), dewpoint_now=9.8)
    assert flagged is False
    assert lowest == pytest.approx(14.0)


def test_dew_is_not_flagged_on_an_exact_tie() -> None:
    night = series(at(22, 19), [1.0] * 4, temps=[12, 10, 10, 11])
    flagged, _lowest = calc.overnight_rewet(night, at(22, 18), dewpoint_now=10.0)
    assert flagged is False


def test_daytime_cold_snaps_are_not_overnight() -> None:
    """A chilly noon is irrelevant to whether dew forms tonight."""
    day = series(at(22, 10), [5.0] * 5, temps=[6, 5, 4, 5, 6])
    _flagged, lowest = calc.overnight_rewet(day, at(22, 9), dewpoint_now=9.8)
    assert lowest == calc.OVERNIGHT_DEFAULT_MIN


def test_hours_beyond_the_horizon_are_ignored() -> None:
    """Tomorrow night's cold is not tonight's problem."""
    far = series(at(23, 20), [1.0] * 4, temps=[2, 1, 1, 2])
    _flagged, lowest = calc.overnight_rewet(far, at(22, 9), dewpoint_now=9.8)
    assert lowest == calc.OVERNIGHT_DEFAULT_MIN


def test_no_dewpoint_reading_means_no_claim() -> None:
    """Better to say nothing than to guess about it."""
    night = series(at(22, 19), [1.0] * 4, temps=[8, 7, 7, 8])
    flagged, _lowest = calc.overnight_rewet(night, at(22, 18), dewpoint_now=None)
    assert flagged is False


def test_overnight_window_is_local_time() -> None:
    """18:00-08:00 is a local-time idea; UTC bucketing would pick wrong hours."""
    night = series(at(22, 18), [1.0] * 3, temps=[9, 8, 7])
    _flagged, lowest = calc.overnight_rewet(night, at(22, 17), dewpoint_now=9.8)
    assert lowest == pytest.approx(7.0)
