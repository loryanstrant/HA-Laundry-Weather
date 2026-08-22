"""Binary sensors: the three yes/no facts worth automating on."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LaundryWeatherCoordinator
from .entity import LaundryWeatherEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LaundryWeatherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GoodDryingDayBinarySensor(coordinator),
            OvernightDewBinarySensor(coordinator),
            CurrentlyRainingBinarySensor(coordinator),
        ]
    )


class GoodDryingDayBinarySensor(LaundryWeatherEntity, BinarySensorEntity):
    """Drives the card's headline.

    Computed here rather than in the card so the headline and the entity can
    never disagree with each other.
    """

    _attr_name = "Good drying day"
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "good_drying_day")

    @property
    def is_on(self) -> bool | None:
        return self.data.get("good_drying_day")


class OvernightDewBinarySensor(LaundryWeatherEntity, BinarySensorEntity):
    """Will dew re-wet anything left out tonight?"""

    _attr_name = "Overnight dew"
    _attr_icon = "mdi:weather-night-partly-cloudy"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "overnight_dew")

    @property
    def is_on(self) -> bool | None:
        return self.data.get("overnight", {}).get("rewet")

    @property
    def extra_state_attributes(self) -> dict:
        overnight = self.data.get("overnight", {})
        return {
            "overnight_minimum": overnight.get("min_temp"),
            "dew_point_now": overnight.get("dewpoint_now"),
        }


class CurrentlyRainingBinarySensor(LaundryWeatherEntity, BinarySensorEntity):
    """Is the exposed line getting wet right now?"""

    _attr_name = "Currently raining"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "currently_raining")

    @property
    def is_on(self) -> bool | None:
        return self.data.get("now", {}).get("wet")
