"""Replay production through the ported model.

The reference implementation is live and answering. This test feeds its exact
recorded inputs through `calc` and asserts the same answers come out — the
single strongest guarantee that the port is faithful rather than merely
plausible.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.laundry_weather import calc

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "reference_snapshot.json").read_text(
        encoding="utf-8"
    )
)
INPUTS = SNAPSHOT["inputs"]
REFERENCE = SNAPSHOT["reference_outputs"]
NEW = SNAPSHOT["expected_new_outputs"]


@pytest.fixture
def outdoor_vpd() -> float:
    return calc.vpd_hpa(INPUTS["outdoor_temperature"], INPUTS["outdoor_humidity"])


@pytest.fixture
def wn() -> float:
    return calc.wind_norm(INPUTS["wind_speed_kmh"])


@pytest.fixture
def room_scores() -> dict[str, float]:
    return {
        room["name"]: calc.indoor_score(room["temperature"], room["humidity"])
        for room in INPUTS["rooms"]
    }


def test_room_score_matches_production(room_scores: dict[str, float]) -> None:
    assert round(room_scores["Sunroom"], 2) == REFERENCE["drying_score_sunroom"]


# The reference implementation read the weather station's own VPD sensor for
# the outdoor spots while computing rooms from temperature and humidity. This
# integration computes every spot the same way, because most stations expose no
# VPD sensor at all and because comparing a room against an outdoor spot is
# only meaningful if both came out of the same formula. The cost is the
# station's 0.0085 hPa firmware difference, which lands on the second decimal
# of a score and can never move a band.
OUTDOOR_TOLERANCE_HPA = 0.02


def test_covered_line_matches_production(outdoor_vpd: float, wn: float) -> None:
    assert calc.covered_score(outdoor_vpd, wn) == pytest.approx(
        REFERENCE["drying_score_covered_line"], abs=OUTDOOR_TOLERANCE_HPA
    )


def test_open_line_matches_production(outdoor_vpd: float, wn: float) -> None:
    """Including the elevation gate, which zeroed the sun term at 8.5°.

    Late afternoon sun was measurably present — a sky fraction of 0.30 — but
    too low to help, and the model is expected to say so.
    """
    factor = calc.live_sun_factor(
        INPUTS["solar_radiation_30m_mean"], INPUTS["sun_elevation"]
    )
    assert factor == pytest.approx(1.0)
    score = calc.open_line_score(outdoor_vpd, wn, factor, wet=False)
    assert score == pytest.approx(
        REFERENCE["drying_score_line_in_sun"], abs=OUTDOOR_TOLERANCE_HPA
    )


def test_outdoor_scores_use_the_same_formula_as_rooms(outdoor_vpd: float) -> None:
    """One formula everywhere, or the ranking compares incompatible numbers."""
    assert outdoor_vpd == calc.indoor_score(
        INPUTS["outdoor_temperature"], INPUTS["outdoor_humidity"]
    )
    assert abs(outdoor_vpd - INPUTS["outdoor_vpd_station"]) < OUTDOOR_TOLERANCE_HPA


def test_the_sun_was_up_but_too_low_to_count() -> None:
    """Guards the distinction between 'no sun' and 'sun at the wrong angle'."""
    assert calc.sky_fraction(
        INPUTS["solar_radiation_30m_mean"], INPUTS["sun_elevation"]
    ) > 0.25
    assert calc.sun_gate(INPUTS["sun_elevation"]) == 0.0


def test_rain_state_reads_as_dry() -> None:
    assert not calc.is_wet_now(
        INPUTS["rain_detector"], INPUTS["rain_dry_state"], INPUTS["rain_rate"]
    )


def test_recommendation_matches_production_for_the_one_room_it_scored(
    outdoor_vpd: float, wn: float, room_scores: dict[str, float]
) -> None:
    """The reference implementation only ever scored the sunroom."""
    label, _score, _best = calc.pick_recommendation(
        {"Sunroom": room_scores["Sunroom"]},
        calc.covered_score(outdoor_vpd, wn),
        calc.open_line_score(outdoor_vpd, wn, 1.0, wet=False),
    )
    assert label == REFERENCE["drying_recommendation"]


def test_advice_reproduces_the_production_string(
    outdoor_vpd: float, wn: float, room_scores: dict[str, float]
) -> None:
    """Character for character, from the recorded inputs."""
    cover = calc.covered_score(outdoor_vpd, wn)
    sun = calc.open_line_score(outdoor_vpd, wn, 1.0, wet=False)
    score = room_scores["Sunroom"]
    advice = calc.build_advice(
        spot="Sunroom",
        score=score,
        band_word=calc.band(score),
        sun=sun,
        cov=cover,
        move_at=None,
        bring_by=datetime.fromisoformat(REFERENCE["bring_in_by"]),
        window_text=REFERENCE["best_window_text"],
        dew=REFERENCE["overnight_rewet"],
        washing_out=INPUTS["washing_on_the_line"],
    )
    assert advice == REFERENCE["drying_advice"]


def test_the_second_room_is_the_gap_this_integration_closes(
    room_scores: dict[str, float]
) -> None:
    """The laundry outscored the sunroom, and production could not say so.

    This is the whole multi-room requirement in one assertion: at the moment
    of capture the reference implementation was recommending the sunroom while
    a better room sat unscored.
    """
    assert round(room_scores["Laundry"], 2) == NEW["drying_score_laundry"]
    assert room_scores["Laundry"] > room_scores["Sunroom"]


def test_recommendation_names_the_better_room_when_both_are_scored(
    outdoor_vpd: float, wn: float, room_scores: dict[str, float]
) -> None:
    label, score, best = calc.pick_recommendation(
        room_scores,
        calc.covered_score(outdoor_vpd, wn),
        calc.open_line_score(outdoor_vpd, wn, 1.0, wet=False),
    )
    assert label == NEW["recommendation_with_both_rooms"]
    assert best == NEW["recommendation_with_both_rooms"]
    assert round(score, 2) == NEW["drying_score_laundry"]


def test_every_spot_is_ranked_with_shape_and_word(
    outdoor_vpd: float, wn: float, room_scores: dict[str, float]
) -> None:
    spots = calc.rank_spots(
        room_scores,
        calc.covered_score(outdoor_vpd, wn),
        calc.open_line_score(outdoor_vpd, wn, 1.0, wet=False),
    )
    assert [s.name for s in spots] == [
        "Laundry",
        "Sunroom",
        calc.OPEN_LINE,
        calc.COVERED_LINE,
    ]
    assert [s.rank for s in spots] == [1, 2, 3, 4]
    # Every row carries a word and a fill meter, never a bare number.
    assert all(spot.band in calc.BAND_NAMES for spot in spots)
    assert all(spot.marks in calc.BAND_MARKS for spot in spots)
