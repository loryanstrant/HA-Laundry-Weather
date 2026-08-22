"""Scoring the hourly forecast — the thing template helpers could never do."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.laundry_weather import calc

from .conftest import TEST_TZ

NOW = datetime(2026, 8, 22, 9, 0, tzinfo=TEST_TZ)


def make_hour(offset_hours: float = 1, **kwargs) -> calc.ForecastHour:
    fields = {
        "temp_c": 18.0,
        "humidity": 55.0,
        "wind_kmh": 10.0,
        "uv_index": 3.0,
        "precip_prob": 0.0,
        "precip_mm": 0.0,
    }
    fields.update(kwargs)
    return calc.ForecastHour(ts=NOW + timedelta(hours=offset_hours), **fields)


TUNING = calc.Tuning()


def test_missing_humidity_is_read_pessimistically() -> None:
    """A gap in the data must never manufacture a drying opportunity."""
    scored = calc.score_forecast_hour(
        make_hour(humidity=None), TUNING, calc.FORECAST_MODEL_UV
    )
    assert scored.vpd == pytest.approx(0.0)


def test_missing_temperature_scores_zero_rather_than_raising() -> None:
    scored = calc.score_forecast_hour(
        make_hour(temp_c=None), TUNING, calc.FORECAST_MODEL_UV
    )
    assert scored.sun == 0.0
    assert scored.cov == 0.0


def test_an_entirely_empty_hour_is_survivable() -> None:
    empty = calc.ForecastHour(ts=NOW + timedelta(hours=1))
    scored = calc.score_forecast_hour(empty, TUNING, calc.FORECAST_MODEL_UV)
    assert scored.sun == 0.0


@pytest.mark.parametrize(
    ("probability", "expected"), [(49.0, False), (50.0, True), (80.0, True)]
)
def test_wet_by_probability(probability: float, expected: bool) -> None:
    assert calc.forecast_is_wet(make_hour(precip_prob=probability)) is expected


@pytest.mark.parametrize(
    ("millimetres", "expected"), [(0.49, False), (0.5, True), (3.0, True)]
)
def test_wet_by_amount(millimetres: float, expected: bool) -> None:
    assert calc.forecast_is_wet(make_hour(precip_mm=millimetres)) is expected


def test_rain_zeroes_the_open_line() -> None:
    scored = calc.score_forecast_hour(
        make_hour(precip_prob=90.0), TUNING, calc.FORECAST_MODEL_UV
    )
    assert scored.sun == 0.0
    assert scored.wet is True


def test_rain_does_not_zero_the_covered_line() -> None:
    """That is the entire point of a roof, and why 'move it under cover' works."""
    scored = calc.score_forecast_hour(
        make_hour(precip_prob=90.0), TUNING, calc.FORECAST_MODEL_UV
    )
    assert scored.cov > 0.0


def test_uv_is_capped() -> None:
    """Above the cap, more UV means more sunburn, not more drying."""
    at_cap = calc.forecast_sun_factor(
        make_hour(uv_index=5.0), TUNING, calc.FORECAST_MODEL_UV
    )
    extreme = calc.forecast_sun_factor(
        make_hour(uv_index=11.0), TUNING, calc.FORECAST_MODEL_UV
    )
    assert at_cap == extreme


def test_uv_model_reproduces_the_reference_formula_at_the_default() -> None:
    """Tuning changes nothing on day one; that is what makes D4 safe."""
    for uv in (0.0, 1.0, 2.5, 5.0, 9.0):
        reference = 1 + 0.6 * min(uv, 5) / 5
        assert calc.forecast_sun_factor(
            make_hour(uv_index=uv), calc.Tuning(), calc.FORECAST_MODEL_UV
        ) == pytest.approx(reference)


def test_the_forecast_scale_moves_with_the_tunable() -> None:
    """Raising the coefficient must not widen the gap to the live scale."""
    doubled = calc.Tuning(sun_coeff=2.4)
    default_factor = calc.forecast_sun_factor(
        make_hour(uv_index=5.0), calc.Tuning(), calc.FORECAST_MODEL_UV
    )
    doubled_factor = calc.forecast_sun_factor(
        make_hour(uv_index=5.0), doubled, calc.FORECAST_MODEL_UV
    )
    assert doubled_factor - 1 == pytest.approx((default_factor - 1) * 2)


def test_cloud_model_is_used_when_the_provider_gives_no_uv() -> None:
    """Met.no returns no UV index at all. Without this the feature is inert."""
    metno_hours = [
        make_hour(offset_hours=n, uv_index=None, cloud_pct=20.0) for n in range(1, 13)
    ]
    assert (
        calc.choose_forecast_sun_model(metno_hours, calc.Tuning())
        == calc.FORECAST_MODEL_CLOUD
    )
    factor = calc.forecast_sun_factor(
        calc.ForecastHour(
            ts=NOW + timedelta(hours=1), cloud_pct=20.0, elevation_deg=50.0
        ),
        calc.Tuning(),
        calc.FORECAST_MODEL_CLOUD,
    )
    assert factor > 1.0


def test_uv_model_is_preferred_when_available() -> None:
    hours = [make_hour(offset_hours=n) for n in range(1, 13)]
    assert (
        calc.choose_forecast_sun_model(hours, calc.Tuning())
        == calc.FORECAST_MODEL_UV
    )


def test_elevation_model_is_the_last_resort() -> None:
    bare = [
        calc.ForecastHour(ts=NOW + timedelta(hours=n), temp_c=18.0, humidity=50.0)
        for n in range(1, 13)
    ]
    assert (
        calc.choose_forecast_sun_model(bare, calc.Tuning())
        == calc.FORECAST_MODEL_ELEVATION
    )


def test_an_explicit_model_choice_overrides_detection() -> None:
    hours = [make_hour(offset_hours=n) for n in range(1, 13)]
    pinned = calc.Tuning(forecast_sun_model=calc.FORECAST_MODEL_CLOUD)
    assert calc.choose_forecast_sun_model(hours, pinned) == calc.FORECAST_MODEL_CLOUD


def test_a_uvless_hour_under_the_uv_model_is_neutral_not_broken() -> None:
    assert calc.forecast_sun_factor(
        make_hour(uv_index=None), TUNING, calc.FORECAST_MODEL_UV
    ) == 1.0


def test_horizon_excludes_the_past() -> None:
    hours = [make_hour(offset_hours=n) for n in (-3, -1, 1, 3)]
    scored, _model = calc.score_forecast(hours, NOW, TUNING)
    assert all(h.ts > NOW for h in scored)
    assert len(scored) == 2


def test_horizon_stops_at_forty_eight_hours() -> None:
    inside = make_hour(offset_hours=47.9)
    outside = make_hour(offset_hours=48.1)
    scored, _model = calc.score_forecast([inside, outside], NOW, TUNING)
    assert [h.ts for h in scored] == [inside.ts]


def test_series_comes_back_in_time_order() -> None:
    shuffled = [make_hour(offset_hours=n) for n in (5, 1, 9, 3)]
    scored, _model = calc.score_forecast(shuffled, NOW, TUNING)
    assert [h.ts for h in scored] == sorted(h.ts for h in scored)


def test_hhmm_is_local_time() -> None:
    """The card prints these directly; a UTC label would be wrong by hours."""
    scored, _model = calc.score_forecast([make_hour(offset_hours=5)], NOW, TUNING)
    assert scored[0].hhmm == "14:00"
