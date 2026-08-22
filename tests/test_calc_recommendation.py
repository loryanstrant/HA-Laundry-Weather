"""Choosing the spot, and the margin that stops it flip-flopping."""

from __future__ import annotations

import pytest

from custom_components.laundry_weather import calc


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
