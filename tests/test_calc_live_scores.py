"""Live scoring: wind, the two outdoor spots, and the sun factor."""

from __future__ import annotations

import pytest

from custom_components.laundry_weather import calc


@pytest.mark.parametrize(
    ("speed", "expected"),
    [(0.0, 0.0), (5.0, 0.25), (10.0, 0.5), (20.0, 1.0), (35.0, 1.0), (None, 0.0)],
)
def test_wind_norm(speed: float | None, expected: float) -> None:
    """Wind helps up to 20 km/h and then stops helping."""
    assert calc.wind_norm(speed) == pytest.approx(expected)


def test_indoor_score_has_no_wind_or_sun_term() -> None:
    """Indoor air is still — the room score is plain VPD."""
    assert calc.indoor_score(20.0, 63.8) == calc.vpd_hpa(20.0, 63.8)


def test_covered_line_keeps_just_over_half_in_still_air() -> None:
    assert calc.covered_score(10.0, 0.0) == pytest.approx(5.5)


def test_covered_line_reaches_full_vpd_at_the_wind_cap() -> None:
    assert calc.covered_score(10.0, 1.0) == pytest.approx(10.0)


def test_open_line_beats_covered_line_in_the_same_air() -> None:
    """A roof kills the breeze and blocks the sun; that must show up."""
    covered = calc.covered_score(10.0, 0.5)
    exposed = calc.open_line_score(10.0, 0.5, calc.live_sun_factor(900.0, 60.0), False)
    assert exposed > covered


def test_sky_fraction_is_zero_when_the_sun_is_on_the_horizon() -> None:
    """Near sunrise the clear-sky value is tiny and the ratio meaningless."""
    assert calc.sky_fraction(30.0, 1.0) == 0.0


def test_sky_fraction_clamps_at_full_sun() -> None:
    # Reflection off cloud edges can briefly exceed the clear-sky model.
    assert calc.sky_fraction(1400.0, 90.0) == 1.0


def test_sky_fraction_reads_cloud_as_a_fraction_of_available_sun() -> None:
    clear = calc.CLEAR_SKY_PEAK  # sin(90°) == 1
    assert calc.sky_fraction(clear * 0.4, 90.0) == pytest.approx(0.4)


def test_sky_fraction_is_zero_without_readings() -> None:
    assert calc.sky_fraction(None, 45.0) == 0.0
    assert calc.sky_fraction(500.0, None) == 0.0


@pytest.mark.parametrize(
    ("elevation", "expected"),
    [(0.0, 0.0), (10.0, 0.0), (25.0, 0.5), (40.0, 1.0), (70.0, 1.0)],
)
def test_sun_gate_ramps_between_ten_and_forty_degrees(
    elevation: float, expected: float
) -> None:
    """Low sun is bright but glancing, so its contribution ramps in."""
    assert calc.sun_gate(elevation) == pytest.approx(expected)


def test_live_sun_factor_tops_out_at_the_documented_ceiling() -> None:
    """Full sun, high in the sky: 1 + 1.2 x 1 x 1."""
    assert calc.live_sun_factor(calc.CLEAR_SKY_PEAK, 90.0) == pytest.approx(2.2)


def test_live_sun_factor_is_neutral_in_the_dark() -> None:
    assert calc.live_sun_factor(0.0, 45.0) == pytest.approx(1.0)


def test_live_sun_factor_scales_with_the_tunable() -> None:
    """Raising the coefficient is how the owner calibrates against real loads."""
    assert calc.live_sun_factor(calc.CLEAR_SKY_PEAK, 90.0, 2.0) == pytest.approx(3.0)


def test_open_line_is_zero_when_it_is_raining() -> None:
    assert calc.open_line_score(15.0, 1.0, 2.2, wet=True) == 0.0


def test_rain_detector_string_comparison_is_forgiving() -> None:
    """The detector's vocabulary is whatever the user's template emits."""
    assert not calc.is_wet_now("No", "No", 0.0)
    assert not calc.is_wet_now(" no ", "No", 0.0)
    assert calc.is_wet_now("Yes", "No", 0.0)
    assert not calc.is_wet_now("Dry", "Dry", 0.0)


def test_unknown_detector_reads_as_dry() -> None:
    """A template sensor with no unique id goes unavailable on every reload.

    Treating that as rain would zero the score repeatedly for no reason; the
    rain rate below is the independent backstop that catches actual rain.
    """
    assert not calc.is_wet_now(None, "No", 0.0)


def test_rain_rate_is_the_backstop() -> None:
    assert calc.is_wet_now(None, "No", 0.5)
    assert not calc.is_wet_now(None, "No", 0.1)


@pytest.mark.parametrize(
    ("score", "expected"),
    [(20.0, "Fast"), (12.0, "Fast"), (11.9, "Moderate"), (6.0, "Moderate"),
     (5.9, "Slow"), (3.0, "Slow"), (2.9, "Barely"), (0.0, "Barely")],
)
def test_band_boundaries(score: float, expected: str) -> None:
    assert calc.band(score) == expected


def test_band_marks_are_shapes_not_colours() -> None:
    """The reader is colour-blind; fill has to carry the meaning."""
    assert calc.band_marks(20.0) == "●●●"
    assert calc.band_marks(8.0) == "●●○"
    assert calc.band_marks(4.0) == "●○○"
    assert calc.band_marks(1.0) == "○○○"


def test_bands_are_configurable() -> None:
    assert calc.band(9.0, (8.0, 4.0, 2.0)) == "Fast"
