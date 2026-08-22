"""Does it actually load, and does it produce the right entities?

These run a real Home Assistant instance from
`pytest-homeassistant-custom-component`, so they catch the things pure model
tests cannot: wiring, unit conversion off real state attributes, and whether
the card's attribute payload is actually there.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.laundry_weather.const import (
    CONF_DEWPOINT,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_RAIN_DETECTOR,
    CONF_RAIN_DRY_STATE,
    CONF_RAIN_RATE,
    CONF_ROOM_HUMIDITY,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMPERATURE,
    CONF_ROOMS,
    CONF_SOLAR_PRESMOOTHED,
    CONF_SOLAR_RADIATION,
    CONF_SUN_ELEVATION,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SPEED,
    DOMAIN,
)

# The production snapshot, so the loaded integration is checked against the
# same readings the pure model tests use.
ENTRY_DATA = {
    "name": "Laundry Weather",
    CONF_WEATHER_ENTITY: "weather.home",
    CONF_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
    CONF_OUTDOOR_HUMIDITY: "sensor.outdoor_humidity",
    CONF_DEWPOINT: "sensor.dewpoint",
    CONF_WIND_SPEED: "sensor.wind_speed",
    CONF_SOLAR_RADIATION: "sensor.solar_radiation",
    CONF_SOLAR_PRESMOOTHED: True,
    CONF_SUN_ELEVATION: "sensor.sun_elevation",
    CONF_RAIN_DETECTOR: "sensor.rain_detector",
    CONF_RAIN_DRY_STATE: "No",
    CONF_RAIN_RATE: "sensor.rain_rate",
}

ROOMS = [
    {
        CONF_ROOM_NAME: "Sunroom",
        CONF_ROOM_TEMPERATURE: "sensor.sunroom_temperature",
        CONF_ROOM_HUMIDITY: "sensor.sunroom_humidity",
    },
    {
        CONF_ROOM_NAME: "Laundry",
        CONF_ROOM_TEMPERATURE: "sensor.laundry_temperature",
        CONF_ROOM_HUMIDITY: "sensor.laundry_humidity",
    },
]


def seed_states(hass: HomeAssistant, **overrides) -> None:
    """Put the production snapshot's readings into the state machine."""
    readings = {
        "sensor.outdoor_temperature": (13.1, {"unit_of_measurement": "°C"}),
        "sensor.outdoor_humidity": (66.0, {"unit_of_measurement": "%"}),
        "sensor.dewpoint": (6.9, {"unit_of_measurement": "°C"}),
        "sensor.wind_speed": (0.4, {"unit_of_measurement": "km/h"}),
        "sensor.solar_radiation": (47.0, {"unit_of_measurement": "W/m²"}),
        "sensor.sun_elevation": (8.5, {"unit_of_measurement": "°"}),
        "sensor.rain_detector": ("No", {}),
        "sensor.rain_rate": (0.0, {"unit_of_measurement": "mm/h"}),
        "sensor.sunroom_temperature": (19.8, {"unit_of_measurement": "°C"}),
        "sensor.sunroom_humidity": (64.3, {"unit_of_measurement": "%"}),
        "sensor.laundry_temperature": (17.6, {"unit_of_measurement": "°C"}),
        "sensor.laundry_humidity": (57.5, {"unit_of_measurement": "%"}),
    }
    readings.update(overrides)
    for entity_id, (state, attrs) in readings.items():
        hass.states.async_set(entity_id, state, attrs)


async def register_forecast(
    hass: HomeAssistant, hours: list[dict] | None = None
) -> None:
    """Stand in for a weather provider's hourly forecast service.

    `weather` is an after-dependency rather than a hard one, so setting the
    entry up does not drag the core component in and re-register the real
    entity service over this stand-in.
    """
    if hours is None:
        start = dt_util.now().replace(minute=0, second=0, microsecond=0)
        hours = [
            {
                "datetime": (start + timedelta(hours=n)).isoformat(),
                "temperature": 18.0 + n % 5,
                "humidity": 50.0,
                "wind_speed": 12.0,
                "uv_index": 3.0,
                "precipitation_probability": 80.0 if n in (6, 7) else 0.0,
                "precipitation": 0.0,
            }
            for n in range(1, 25)
        ]

    async def _get_forecasts(call):
        return {"weather.home": {"forecast": hours}}

    hass.services.async_register(
        "weather",
        "get_forecasts",
        _get_forecasts,
        supports_response=SupportsResponse.ONLY,
    )
    hass.states.async_set("weather.home", "sunny", {})


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Home Assistant's own `sun` component leaves a platform poll timer.

    Verified by setting `sun` up alone in an otherwise empty test: the timer
    appears with none of this integration loaded. `sun` is a hard dependency
    here because the sun's height is what separates "the line in the sun" from
    "the line under cover", so the timer comes with the territory.
    """
    return True


@pytest.fixture
async def loaded_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A fully set-up integration with two rooms."""
    await async_setup_component(hass, "homeassistant", {})
    seed_states(hass)
    await register_forecast(hass)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Laundry Weather",
        data=ENTRY_DATA,
        options={CONF_ROOMS: ROOMS},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_it_loads(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    assert loaded_entry.entry_id in hass.data[DOMAIN]


async def test_a_sensor_exists_for_every_room(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Two rooms, two sensors — the gap the reference implementation had."""
    assert hass.states.get("sensor.laundry_weather_sunroom_drying_score") is not None
    assert hass.states.get("sensor.laundry_weather_laundry_drying_score") is not None


async def test_room_scores_match_the_model(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    sunroom = hass.states.get("sensor.laundry_weather_sunroom_drying_score")
    laundry = hass.states.get("sensor.laundry_weather_laundry_drying_score")
    assert float(sunroom.state) == pytest.approx(8.24, abs=0.01)
    assert float(laundry.state) == pytest.approx(8.55, abs=0.01)


async def test_the_better_room_is_recommended(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    state = hass.states.get("sensor.laundry_weather_recommendation")
    assert state.state == "Laundry"


async def test_bring_in_by_always_has_a_value(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The regression, checked end to end rather than only in the model."""
    bring_in = hass.states.get("sensor.laundry_weather_bring_in_by")
    assert bring_in.state not in ("unknown", "unavailable", "None")
    assert dt_util.parse_datetime(bring_in.state) is not None


async def test_move_outside_at_is_a_real_none_not_the_word(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """'Not worth it today' must not render as the string 'None'."""
    state = hass.states.get("sensor.laundry_weather_move_outside_at")
    assert state.state != "None"


async def test_the_card_payload_is_on_the_recommendation_sensor(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """One entity to configure; everything else rides on its attributes."""
    attrs = hass.states.get("sensor.laundry_weather_recommendation").attributes
    for key in ("spots", "forecast", "timings", "overnight", "now", "config"):
        assert key in attrs, f"the card needs {key}"

    assert len(attrs["spots"]) == 4  # two rooms plus both line positions
    assert [s["rank"] for s in attrs["spots"]] == [1, 2, 3, 4]
    assert all(s["band"] for s in attrs["spots"])
    assert all(s["marks"] for s in attrs["spots"])


async def test_the_forecast_series_is_charted_shaped(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The thing template helpers could never expose."""
    series = hass.states.get("sensor.laundry_weather_recommendation").attributes[
        "forecast"
    ]
    assert len(series) >= 12
    for hour in series:
        assert set(hour) == {"ts", "hhmm", "sun", "cov", "wet"}
    assert any(hour["wet"] for hour in series), "the seeded rain should appear"


async def test_the_forecast_payload_fits_under_the_recorder_limit(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Home Assistant drops attributes over 16 KB."""
    attrs = dict(
        hass.states.get("sensor.laundry_weather_recommendation").attributes
    )
    size = len(json.dumps(attrs, default=str).encode("utf-8"))
    assert size < 16384, f"attribute payload is {size} bytes"


async def test_large_attributes_are_kept_out_of_the_recorder(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Rewriting 48 forecast hours every two minutes would batter the database."""
    from custom_components.laundry_weather.sensor import RecommendationSensor

    for key in ("forecast", "spots", "now", "timings"):
        assert key in RecommendationSensor._unrecorded_attributes


async def test_binary_sensors_exist(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert hass.states.get("binary_sensor.laundry_weather_good_drying_day")
    assert hass.states.get("binary_sensor.laundry_weather_overnight_dew")
    assert hass.states.get("binary_sensor.laundry_weather_currently_raining")


async def test_the_washing_switch_changes_the_advice(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """Turning it on shifts the emphasis to when to rescue the load."""
    before = hass.states.get("sensor.laundry_weather_advice").state
    assert not before.startswith("Washing is out")

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.laundry_weather_washing_on_the_line"},
        blocking=True,
    )
    await hass.async_block_till_done()

    after = hass.states.get("sensor.laundry_weather_advice").state
    assert after.startswith("Washing is out")


async def test_advice_never_exceeds_the_state_limit(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert len(hass.states.get("sensor.laundry_weather_advice").state) <= 255


async def test_fahrenheit_and_mph_are_converted(hass: HomeAssistant) -> None:
    """A US setup must not be silently scored as if 70 were Celsius."""
    await async_setup_component(hass, "homeassistant", {})
    seed_states(
        hass,
        **{
            "sensor.outdoor_temperature": (55.58, {"unit_of_measurement": "°F"}),
            "sensor.wind_speed": (10.0, {"unit_of_measurement": "mph"}),
        },
    )
    await register_forecast(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, title="LW", data=ENTRY_DATA, options={CONF_ROOMS: ROOMS}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.data["now"]["temp_out"] == pytest.approx(13.1, abs=0.05)
    assert coordinator.data["now"]["wind_kmh"] == pytest.approx(16.09, abs=0.01)


async def test_an_unavailable_sensor_is_reported_not_guessed(
    hass: HomeAssistant,
) -> None:
    """Unavailable is not zero, and must never be scored as though it were."""
    await async_setup_component(hass, "homeassistant", {})
    seed_states(hass, **{"sensor.wind_speed": ("unavailable", {})})
    await register_forecast(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, title="LW", data=ENTRY_DATA, options={CONF_ROOMS: ROOMS}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.data["now"]["wind_kmh"] is None
    assert "sensor.wind_speed" in coordinator.data["diagnostics"]["missing"]


async def test_a_room_with_a_flat_battery_drops_out_of_the_ranking(
    hass: HomeAssistant,
) -> None:
    """Better to omit a room than to rank it last on a missing reading."""
    await async_setup_component(hass, "homeassistant", {})
    seed_states(hass, **{"sensor.laundry_humidity": ("unavailable", {})})
    await register_forecast(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, title="LW", data=ENTRY_DATA, options={CONF_ROOMS: ROOMS}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.data["recommendation"] == "Sunroom"
    names = [spot["name"] for spot in coordinator.data["spots"]]
    assert "Laundry" not in names


async def test_a_provider_without_uv_still_gets_a_sun_model(
    hass: HomeAssistant,
) -> None:
    """Met.no returns no UV index. Without the fallback, timings never fire."""
    await async_setup_component(hass, "homeassistant", {})
    seed_states(hass)
    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    metno = [
        {
            "datetime": (start + timedelta(hours=n)).isoformat(),
            "temperature": 20.0,
            "humidity": 45.0,
            "wind_speed": 12.0,
            "cloud_coverage": 10.0,
            "precipitation": 0.0,
        }
        for n in range(1, 25)
    ]
    await register_forecast(hass, metno)
    entry = MockConfigEntry(
        domain=DOMAIN, title="LW", data=ENTRY_DATA, options={CONF_ROOMS: ROOMS}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.data["forecast_meta"]["sun_model"] == "cloud"
    assert coordinator.data["forecast_meta"]["count"] > 0


async def test_a_provider_with_naive_timestamps_still_produces_a_forecast(
    hass: HomeAssistant,
) -> None:
    """The Bureau of Meteorology returns bare local times, with no offset.

    Every synthetic fixture in this suite builds its timestamps with
    `.isoformat()` on a tz-aware datetime, so they all carry an offset and this
    went unnoticed until the integration was run against a real BOM feed on
    DEV: all 73 forecast hours were rejected and the timing lines came back
    empty. Home Assistant's own convention is that a naive datetime is local.
    """
    await async_setup_component(hass, "homeassistant", {})
    seed_states(hass)
    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    bom = [
        {
            # Exactly the shape the Bureau returns — note the missing offset.
            "datetime": (start + timedelta(hours=n)).strftime("%Y-%m-%dT%H:%M:%S"),
            "condition": "cloudy",
            "temperature": 18.0,
            "humidity": 55.0,
            "wind_speed": 11.0,
            "wind_gust_speed": 20.0,
            "uv_index": 3.0,
            "precipitation_probability": 10.0,
            "precipitation": 0.0,
        }
        for n in range(1, 25)
    ]
    await register_forecast(hass, bom)
    entry = MockConfigEntry(
        domain=DOMAIN, title="LW", data=ENTRY_DATA, options={CONF_ROOMS: ROOMS}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.data["forecast_meta"]["count"] > 0, (
        "naive timestamps were dropped — the whole forecast is gone"
    )
    assert not coordinator.data["diagnostics"]["missing"]
    # And they must land on the right hour, not be shifted by the UTC offset.
    first = coordinator.data["forecast"][0]
    assert first["hhmm"] == (start + timedelta(hours=1)).strftime("%H:%M")


async def test_unload(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.entry_id not in hass.data.get(DOMAIN, {})
