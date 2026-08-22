"""Vapour pressure deficit — the foundation the whole model stands on."""

from __future__ import annotations

import pytest

from custom_components.laundry_weather import calc

# Captured simultaneously from the reference weather station, which computes
# its own vapour pressure deficit in firmware. Reproducing it is what justifies
# trusting the formula for rooms and forecast hours, where no station reading
# exists to check against.
#
# The agreement is 0.0085 hPa, not exact: the station's firmware uses a
# slightly different saturation constant. That is an order of magnitude below
# the display precision and two orders below the width of a drying band, so it
# cannot change an answer — but the tolerance here states it honestly rather
# than asserting a match that does not exist.
STATION_READINGS = [
    # (temperature °C, relative humidity %, station VPD hPa)
    (13.1, 66.0, 5.11344684691491),
]

STATION_TOLERANCE_HPA = 0.02


@pytest.mark.parametrize(("temp", "rh", "expected"), STATION_READINGS)
def test_matches_station_reading(temp: float, rh: float, expected: float) -> None:
    assert calc.vpd_hpa(temp, rh) == pytest.approx(expected, abs=STATION_TOLERANCE_HPA)


def test_station_agreement_is_far_finer_than_a_band() -> None:
    """The residual has to be small enough that it can never move a band."""
    temp, rh, station = STATION_READINGS[0]
    residual = abs(calc.vpd_hpa(temp, rh) - station)
    narrowest_band = min(
        calc.DEFAULT_BANDS[0] - calc.DEFAULT_BANDS[1],
        calc.DEFAULT_BANDS[1] - calc.DEFAULT_BANDS[2],
    )
    assert residual < narrowest_band / 100


def test_saturated_air_has_no_deficit() -> None:
    assert calc.vpd_hpa(20.0, 100.0) == pytest.approx(0.0)


def test_bone_dry_air_gives_full_saturation_pressure() -> None:
    # At 0% humidity the deficit is the whole saturation vapour pressure.
    assert calc.vpd_hpa(0.0, 0.0) == pytest.approx(6.112, abs=0.001)


def test_rises_with_temperature() -> None:
    values = [calc.vpd_hpa(t, 50.0) for t in (5.0, 15.0, 25.0, 35.0)]
    assert values == sorted(values)


def test_falls_with_humidity() -> None:
    values = [calc.vpd_hpa(20.0, rh) for rh in (10.0, 40.0, 70.0, 95.0)]
    assert values == sorted(values, reverse=True)


def test_humidity_is_clamped_not_trusted() -> None:
    # Sensors do report 101%; that must not produce a negative deficit.
    assert calc.vpd_hpa(20.0, 105.0) == pytest.approx(0.0)
    assert calc.vpd_hpa(20.0, -5.0) == calc.vpd_hpa(20.0, 0.0)


def test_below_freezing_still_computes() -> None:
    assert calc.vpd_hpa(-5.0, 80.0) > 0.0


def test_cold_dry_air_beats_warm_humid_air() -> None:
    """The counter-intuitive result the whole model exists to surface."""
    cold_and_dry = calc.vpd_hpa(10.0, 30.0)
    warm_and_humid = calc.vpd_hpa(25.0, 85.0)
    assert cold_and_dry > warm_and_humid
