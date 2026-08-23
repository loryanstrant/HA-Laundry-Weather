"""Choosing the spot, and the margin that stops it flip-flopping."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.laundry_weather import calc

from .conftest import TEST_TZ


def test_outside_must_win_by_the_margin() -> None:
    """Marginally better outside is not worth carrying a basket for.

    Without this, passing cloud swings the sun score either side of the room
    score and the recommendation changes every few minutes.
    """
    rooms = {"Sunroom": 10.0}

    label, _score, _best = calc.pick_recommendation(rooms, 3.0, 11.4)
    assert label == "Sunroom"

    label, _score, _best = calc.pick_recommendation(rooms, 3.0, 11.6)
    assert label == calc.OPEN_LINE


def test_the_open_line_must_also_beat_the_covered_line() -> None:
    """Rain zeroes the sun score; cover should then win outright."""
    label, _score, _best = calc.pick_recommendation({"Sunroom": 1.0}, 8.0, 0.0)
    assert label == calc.COVERED_LINE


def test_the_better_of_two_rooms_is_named() -> None:
    rooms = {"Sunroom": 8.24, "Laundry": 8.55}
    label, score, best = calc.pick_recommendation(rooms, 2.86, 4.15)
    assert label == "Laundry"
    assert best == "Laundry"
    assert score == pytest.approx(8.55)


def test_many_rooms_are_supported() -> None:
    rooms = {"Sunroom": 6.0, "Laundry": 9.0, "Spare room": 7.5, "Garage": 4.0}
    label, score, _best = calc.pick_recommendation(rooms, 3.0, 3.5)
    assert label == "Laundry"
    assert score == pytest.approx(9.0)


def test_covered_line_wins_when_every_room_is_worse() -> None:
    label, _score, best = calc.pick_recommendation({"Sunroom": 2.0}, 5.0, 1.0)
    assert label == calc.COVERED_LINE
    # The best room is still reported, so the card can show the comparison.
    assert best == "Sunroom"


def test_no_rooms_configured_still_answers() -> None:
    """Someone with only a washing line is a valid setup."""
    label, score, best = calc.pick_recommendation({}, 4.0, 9.0)
    assert label == calc.OPEN_LINE
    assert score == pytest.approx(9.0)
    assert best is None


def test_the_margin_is_configurable() -> None:
    rooms = {"Sunroom": 10.0}
    relaxed = calc.pick_recommendation(rooms, 3.0, 10.5, margin=1.0)[0]
    assert relaxed == calc.OPEN_LINE
    strict = calc.pick_recommendation(rooms, 3.0, 10.5, margin=1.4)[0]
    assert strict == "Sunroom"


def test_a_dead_calm_zero_score_day_does_not_crash() -> None:
    label, score, _best = calc.pick_recommendation({"Sunroom": 0.0}, 0.0, 0.0)
    assert label in (calc.OPEN_LINE, calc.COVERED_LINE, "Sunroom")
    assert score == 0.0


def test_good_drying_day_is_about_outdoors() -> None:
    """A rainy day with a superb sunroom is not a good day to dry.

    The headline sits above a picture; saying "a good day to dry" while it
    rains would read as nonsense whatever the sunroom is doing.
    """
    assert not calc.good_drying_day(sun=0.0, cov=2.0, wet=True)
    assert calc.good_drying_day(sun=9.0, cov=5.0, wet=False)
    assert not calc.good_drying_day(sun=4.0, cov=3.0, wet=False)


def test_good_drying_day_takes_the_better_outdoor_spot() -> None:
    """Overcast but breezy: cover alone can carry the day."""
    assert calc.good_drying_day(sun=1.0, cov=7.0, wet=False)


# --- the verdict is about the day, not the moment ----------------------------


def _hours(
    start: datetime,
    suns: list[float],
    wet: bool = False,
    cov: float | None = None,
):
    """A scored series starting at `start`, one hour apart.

    `cov` can be set independently of `sun` because that is exactly what rain
    does to a real hour: the exposed line goes to zero and the covered line
    carries on.
    """
    return [
        calc.ScoredHour(
            ts=start + timedelta(hours=i),
            hhmm=(start + timedelta(hours=i)).strftime("%H:%M"),
            sun=sun,
            cov=sun * 0.4 if cov is None else cov,
            wet=wet,
            vpd=sun,
            temp_c=18.0,
        )
        for i, sun in enumerate(suns)
    ]


def test_a_cold_still_morning_with_a_good_afternoon_is_a_good_day() -> None:
    """The bug this fixes, with the numbers that produced it.

    On prod at 10:06 the exposed line scored 5.56 and the covered line 3.0 —
    13.8 C, 65% RH and dead still air — so the headline read "It Is Not a Good
    Day to Dry". The same payload said the day peaked at 16.6 between 11:00 and
    16:00 and told the user to move the washing out at noon.
    """
    morning = datetime(2026, 8, 23, 10, 0, tzinfo=TEST_TZ)
    sunset = datetime(2026, 8, 23, 17, 54, tzinfo=TEST_TZ)
    series = _hours(morning, [7.0, 12.0, 16.6, 15.0, 11.0, 6.0, 3.0])

    peak = calc.rest_of_today_peak(series, sunset)
    assert peak == pytest.approx(16.6)
    assert calc.good_drying_day(sun=5.56, cov=3.0, wet=False, today_peak=peak)


def test_a_good_tomorrow_does_not_rescue_tonight() -> None:
    """The trap that produced the "bring in by, in 52 minutes" bug.

    After dark the sunset handed to `assess` is *tomorrow's*, so bounding the
    scan by it stops bounding anything. `day_over` is what actually ends the
    day — reading the bound alone would announce a glorious Sunday at nine
    o'clock on Saturday night.
    """
    tonight = datetime(2026, 8, 22, 21, 0, tzinfo=TEST_TZ)
    tomorrow_sunset = datetime(2026, 8, 23, 17, 54, tzinfo=TEST_TZ)
    series = _hours(tonight, [0.0] * 12 + [4.0, 9.0, 18.0, 17.0])

    assert calc.rest_of_today_peak(series, tomorrow_sunset, day_over=True) == 0.0
    assert not calc.good_drying_day(sun=0.0, cov=0.0, wet=False, today_peak=0.0)

    # And without the guard the bound is useless, which is the whole point.
    assert calc.rest_of_today_peak(series, tomorrow_sunset) == pytest.approx(18.0)


def test_hours_after_sunset_are_not_part_of_today() -> None:
    """A warm evening is not drying time — the sun has gone."""
    afternoon = datetime(2026, 8, 23, 16, 0, tzinfo=TEST_TZ)
    sunset = datetime(2026, 8, 23, 17, 54, tzinfo=TEST_TZ)
    series = _hours(afternoon, [4.0, 3.0, 20.0, 20.0])  # 18:00 and 19:00 are late

    assert calc.rest_of_today_peak(series, sunset) == pytest.approx(4.0)


def test_a_wet_day_is_not_rescued_by_the_covered_line() -> None:
    """The roof keeps working; the day is still not a good day to dry.

    Covered scores are deliberately not zeroed by rain elsewhere in the model —
    "move it under cover" has to stay useful advice — so the day verdict has to
    skip wet hours itself.
    """
    morning = datetime(2026, 8, 23, 9, 0, tzinfo=TEST_TZ)
    sunset = datetime(2026, 8, 23, 17, 54, tzinfo=TEST_TZ)
    # Rain all day: the exposed line is zeroed, the veranda is comfortably in
    # the Moderate band, which is what would carry the verdict if wet hours
    # were scored.
    drizzle = _hours(morning, [0.0] * 8, wet=True, cov=8.0)

    assert calc.rest_of_today_peak(drizzle, sunset) == 0.0
    assert not calc.good_drying_day(sun=0.0, cov=8.0, wet=True, today_peak=0.0)


def test_a_thin_forecast_cannot_argue_with_a_good_afternoon() -> None:
    """Live scores stay in the comparison as a floor.

    If it is demonstrably drying well right now, no amount of missing or
    pessimistic forecast should talk the headline out of it.
    """
    assert calc.good_drying_day(sun=13.0, cov=4.0, wet=False, today_peak=0.0)


def test_rain_right_now_still_wins() -> None:
    """Whatever the afternoon holds, do not put a cheerful mascot over rain."""
    assert not calc.good_drying_day(sun=0.0, cov=2.0, wet=True, today_peak=20.0)
