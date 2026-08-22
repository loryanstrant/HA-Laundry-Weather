"""The setup and settings screens."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.laundry_weather.const import (
    CONF_ADD_ANOTHER,
    CONF_BAND_FAST,
    CONF_BAND_MODERATE,
    CONF_BAND_SLOW,
    CONF_BRING_IN_FLOOR,
    CONF_FORECAST_SUN_MODEL,
    CONF_KLINGON,
    CONF_NAME,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_OUTSIDE_MARGIN,
    CONF_RAIN_DRY_STATE,
    CONF_REMOVE_ROOMS,
    CONF_ROOM_HUMIDITY,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMPERATURE,
    CONF_ROOMS,
    CONF_SUN_COEFF,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)

from .test_integration import ENTRY_DATA, ROOMS


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """See test_integration — Home Assistant's own sun component leaves one."""
    return True


async def _walk_to_rooms(hass: HomeAssistant) -> str:
    """Run the flow up to the first room question."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Laundry Weather", CONF_WEATHER_ENTITY: "weather.home"},
    )
    assert result["step_id"] == "outdoor"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
            CONF_OUTDOOR_HUMIDITY: "sensor.outdoor_humidity",
        },
    )
    assert result["step_id"] == "sun"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "rain"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "room"
    return result["flow_id"]


async def test_the_flow_walks_every_step(hass: HomeAssistant) -> None:
    flow_id = await _walk_to_rooms(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ROOM_NAME: "Sunroom",
            CONF_ROOM_TEMPERATURE: "sensor.sunroom_temperature",
            CONF_ROOM_HUMIDITY: "sensor.sunroom_humidity",
            CONF_ADD_ANOTHER: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Laundry Weather"
    assert len(result["options"][CONF_ROOMS]) == 1


async def test_more_than_one_room_can_be_added(hass: HomeAssistant) -> None:
    """The whole reason this is not the reference implementation."""
    flow_id = await _walk_to_rooms(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ROOM_NAME: "Sunroom",
            CONF_ROOM_TEMPERATURE: "sensor.sunroom_temperature",
            CONF_ROOM_HUMIDITY: "sensor.sunroom_humidity",
            CONF_ADD_ANOTHER: True,
        },
    )
    assert result["step_id"] == "room", "ticking add-another should loop"

    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ROOM_NAME: "Laundry",
            CONF_ROOM_TEMPERATURE: "sensor.laundry_temperature",
            CONF_ROOM_HUMIDITY: "sensor.laundry_humidity",
            CONF_ADD_ANOTHER: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    names = [r[CONF_ROOM_NAME] for r in result["options"][CONF_ROOMS]]
    assert names == ["Sunroom", "Laundry"]


async def test_a_room_needs_a_name(hass: HomeAssistant) -> None:
    flow_id = await _walk_to_rooms(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ROOM_NAME: "   ",
            CONF_ROOM_TEMPERATURE: "sensor.sunroom_temperature",
            CONF_ROOM_HUMIDITY: "sensor.sunroom_humidity",
            CONF_ADD_ANOTHER: False,
        },
    )
    assert result["errors"] == {CONF_ROOM_NAME: "empty_room_name"}


async def test_two_rooms_cannot_share_a_name(hass: HomeAssistant) -> None:
    """Otherwise their entity ids collide and one silently wins."""
    flow_id = await _walk_to_rooms(hass)
    await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ROOM_NAME: "Sunroom",
            CONF_ROOM_TEMPERATURE: "sensor.sunroom_temperature",
            CONF_ROOM_HUMIDITY: "sensor.sunroom_humidity",
            CONF_ADD_ANOTHER: True,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ROOM_NAME: "sunroom",
            CONF_ROOM_TEMPERATURE: "sensor.laundry_temperature",
            CONF_ROOM_HUMIDITY: "sensor.laundry_humidity",
            CONF_ADD_ANOTHER: False,
        },
    )
    assert result["errors"] == {CONF_ROOM_NAME: "duplicate_room_name"}


async def test_the_optional_steps_can_be_skipped(hass: HomeAssistant) -> None:
    """Someone with no weather station still gets a working setup."""
    flow_id = await _walk_to_rooms(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_ROOM_NAME: "Sunroom",
            CONF_ROOM_TEMPERATURE: "sensor.sunroom_temperature",
            CONF_ROOM_HUMIDITY: "sensor.sunroom_humidity",
            CONF_ADD_ANOTHER: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The rain dry-state default has to survive, or a blank comparison string
    # would read every reading as rain.
    assert result["data"][CONF_RAIN_DRY_STATE] == "No"


# --- options ---------------------------------------------------------------


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Laundry Weather",
        data=ENTRY_DATA,
        options={CONF_ROOMS: list(ROOMS)},
    )
    entry.add_to_hass(hass)
    return entry


async def test_the_options_menu_offers_every_section(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "tuning",
        "display",
        "add_room",
        "remove_room",
        "sensors",
    }


async def test_tuning_saves_the_sun_coefficient(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The knob the owner actually wants, for calibrating against real loads."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "tuning"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SUN_COEFF: 1.6,
            CONF_OUTSIDE_MARGIN: 1.2,
            CONF_BRING_IN_FLOOR: 3.0,
            CONF_BAND_FAST: 12,
            CONF_BAND_MODERATE: 6,
            CONF_BAND_SLOW: 3,
            CONF_FORECAST_SUN_MODEL: "auto",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SUN_COEFF] == 1.6
    # Rooms must survive an unrelated edit.
    assert len(result["data"][CONF_ROOMS]) == 2


async def test_bands_must_descend(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Fast below Moderate would name every band wrongly, silently."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "tuning"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SUN_COEFF: 1.2,
            CONF_OUTSIDE_MARGIN: 1.15,
            CONF_BRING_IN_FLOOR: 2.5,
            CONF_BAND_FAST: 4,
            CONF_BAND_MODERATE: 6,
            CONF_BAND_SLOW: 3,
            CONF_FORECAST_SUN_MODEL: "auto",
        },
    )
    assert result["errors"] == {"base": "bands_not_descending"}


async def test_the_klingon_toggle_round_trips(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "display"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_KLINGON: True}
    )
    assert result["data"][CONF_KLINGON] is True


async def test_a_room_can_be_added_later(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ROOM_NAME: "Spare room",
            CONF_ROOM_TEMPERATURE: "sensor.spare_temperature",
            CONF_ROOM_HUMIDITY: "sensor.spare_humidity",
            CONF_ADD_ANOTHER: False,
        },
    )
    names = [r[CONF_ROOM_NAME] for r in result["data"][CONF_ROOMS]]
    assert names == ["Sunroom", "Laundry", "Spare room"]


async def test_a_room_can_be_removed(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_REMOVE_ROOMS: ["Laundry"]}
    )
    names = [r[CONF_ROOM_NAME] for r in result["data"][CONF_ROOMS]]
    assert names == ["Sunroom"]


async def test_removing_nothing_changes_nothing(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_REMOVE_ROOMS: []}
    )
    assert len(result["data"][CONF_ROOMS]) == 2
