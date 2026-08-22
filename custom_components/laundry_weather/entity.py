"""Shared entity base — one device per configured setup."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import LaundryWeatherCoordinator


class LaundryWeatherEntity(CoordinatorEntity[LaundryWeatherCoordinator]):
    """Every entity hangs off one device, so the setup reads as one thing."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LaundryWeatherCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="loryanstrant",
            model="Drying conditions",
            sw_version=INTEGRATION_VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def data(self) -> dict:
        return self.coordinator.data or {}
