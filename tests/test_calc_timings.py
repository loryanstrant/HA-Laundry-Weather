"""When to take it out, and when to bring it in.

The first test in this file is the reason the file exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.laundry_weather import calc

from .conftest import TEST_TZ


def hour(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 22, h, m, tzinfo=TEST_TZ)


def series(*pairs: tuple[int, float, float]) -> list[calc.ScoredHour]:
    """Build a scored series from (hour, sun, cover) triples."""
    return [
        calc.ScoredHour(
            ts=hour(h),
            hhmm=f"{h:02d}:00",
            sun=sun,
            cov=cov,
            wet=False,
            vpd=max(sun, cov),
            temp_c=18.0,
        )
        for h, sun, cov in pairs
    ]


SUNSET = hour(17, 51)


def test_bring_in_by_is_independent_of_move_outside_at() -> None:
    """The regression this integration was partly built to prevent.

    In the reference implementation the bring-in time was gated on the
    move-outside time having found a slot. So on a day when going outside was
    never worthwhile, the bring-in time was wiped — exactly the day when
    washing is already on the line and the only question that matters is when
    to rescue it.

    Here: a series where nothing ever beats a strong indoor room, so
    `move_outside_at` is correctly None. `bring_in_by` must still answer.
    """
    strong_indoor = 12.0
    drying_day = series(
        (10, 4.0, 3.0),
        (12, 5.0, 3.5),
        (14, 4.0, 3.0),
        (16, 1.0, 1.2),  # both spots give up here
    )

    assert calc.move_outside_at(drying_day, strong_indoor, SUNSET) is None

    bring_by, source = calc.bring_in_by(drying_day, SUNSET)
    assert bring_by == hour(16)
    assert source == "score_drop"


def test_bring_in_by_takes_no_move_at_argument() -> None:
    """Enforced at the signature, so the coupling cannot come back quietly."""
    import inspect

    parameters = set(inspect.signature(calc.bring_in_by).parameters)
    assert "move_at" not in parameters
    assert "move_outside_at" not in parameters


@pytest.mark.parametrize("indoor", [0.0, 5.0, 12.0, 99.0])
def test_bring_in_by_never_returns_none(indoor: float) -> None:
    """Whatever the day looks like, there is always an answer."""
    for shape in (
        series((10, 0.0, 0.0), (12, 0.0, 0.0)),
        series((10, 20.0, 18.0), (12, 22.0, 19.0)),
        series((10, 4.0, 1.0), (12, 1.0, 4.0)),
        [],
    ):
        bring_by, source = calc.bring_in_by(shape, SUNSET)
        assert isinstance(bring_by, datetime)
        assert source in ("score_drop", "sunset")


def test_bring_in_by_falls_back_to_sunset_when_drying_never_stops() -> None:
    good_all_day = series((10, 9.0, 7.0), (14, 11.0, 8.0), (16, 8.0, 6.0))
    bring_by, source = calc.bring_in_by(good_all_day, SUNSET)
    assert bring_by == SUNSET
    assert source == "sunset"


def test_bring_in_by_uses_the_better_of_the_two_positions() -> None:
    """The line is movable, so either position still drying is a reason to wait."""
    rain_on_the_open_line = series((12, 0.0, 4.0), (14, 0.0, 4.0), (16, 0.0, 0.5))
    bring_by, _ = calc.bring_in_by(rain_on_the_open_line, SUNSET)
    assert bring_by == hour(16)


def test_bring_in_by_ignores_hours_after_dark() -> None:
    """Everything scores badly at 22:00; that is not a bring-in time."""
    day = series((12, 9.0, 7.0), (16, 8.0, 6.0), (22, 0.1, 0.1))
    bring_by, source = calc.bring_in_by(day, SUNSET)
    assert bring_by == SUNSET
    assert source == "sunset"


def test_move_outside_at_finds_the_first_worthwhile_hour() -> None:
    day = series((10, 5.0, 3.0), (12, 14.0, 6.0), (14, 16.0, 7.0))
    assert calc.move_outside_at(day, 10.0, SUNSET) == hour(12)


def test_move_outside_at_respects_the_margin() -> None:
    """Beating indoors by a whisker is not worth carrying a basket outside."""
    indoor = 10.0
    marginal = series((12, 11.0, 4.0))
    assert calc.move_outside_at(marginal, indoor, SUNSET) is None

    convincing = series((12, 11.6, 4.0))
    assert calc.move_outside_at(convincing, indoor, SUNSET) == hour(12)


def test_move_outside_at_is_none_when_it_is_never_worth_it() -> None:
    day = series((10, 3.0, 2.0), (12, 4.0, 2.5))
    assert calc.move_outside_at(day, 12.0, SUNSET) is None


def test_move_outside_at_ignores_hours_after_sunset() -> None:
    """A brilliant forecast for 21:00 is not an instruction to go outside."""
    day = series((19, 30.0, 20.0), (21, 40.0, 25.0))
    assert calc.move_outside_at(day, 5.0, SUNSET) is None


def test_an_empty_forecast_still_produces_a_bring_in_time() -> None:
    """No forecast is a reason to fall back, not a reason to answer nothing."""
    bring_by, source = calc.bring_in_by([], SUNSET)
    assert bring_by == SUNSET
    assert source == "sunset"
    assert calc.move_outside_at([], 5.0, SUNSET) is None


def test_bring_in_floor_is_configurable() -> None:
    day = series((12, 4.0, 3.0), (14, 3.5, 2.0))
    assert calc.bring_in_by(day, SUNSET, floor=2.5)[0] == SUNSET
    assert calc.bring_in_by(day, SUNSET, floor=4.5)[0] == hour(12)


def test_timings_survive_a_series_that_starts_after_sunset() -> None:
    """Asking in the evening must not produce a nonsense answer."""
    tomorrow = [
        calc.ScoredHour(
            ts=SUNSET + timedelta(hours=n),
            hhmm="00:00",
            sun=5.0,
            cov=4.0,
            wet=False,
            vpd=5.0,
            temp_c=15.0,
        )
        for n in range(1, 6)
    ]
    bring_by, source = calc.bring_in_by(tomorrow, SUNSET)
    assert bring_by == SUNSET
    assert source == "sunset"
