"""The 'washing is on the line' switch.

Owned by the integration so the card is one tap and nobody has to build a
helper first. Setups that already have an `input_boolean` driving automations
can point at it instead, via the external washing entity option.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import LaundryWeatherCoordinator
from .entity import LaundryWeatherEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LaundryWeatherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WashingOnTheLineSwitch(coordinator)])


class WashingOnTheLineSwitch(LaundryWeatherEntity, SwitchEntity, RestoreEntity):
    """Changes what the advice emphasises, not what the model computes."""

    _attr_name = "Washing on the line"
    _attr_icon = "mdi:tshirt-crew-outline"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "washing_on_the_line")

    async def async_added_to_hass(self) -> None:
        """Restore the previous answer — a restart does not empty the line."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == "on":
            await self.coordinator.async_set_washing_out(True)

    @property
    def is_on(self) -> bool:
        return bool(self.data.get("washing_out"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_washing_out(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_washing_out(False)
