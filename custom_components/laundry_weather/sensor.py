"""Sensors: the scores, the verdict, the advice and the timings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPressure
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_ROOM_NAME, DOMAIN
from .coordinator import LaundryWeatherCoordinator, slugify_room
from .entity import LaundryWeatherEntity

#: Attribute keys big enough to be worth keeping out of the recorder. The
#: forecast series is rewritten every couple of minutes; recording it would be
#: brutal on the database and nobody wants its history.
UNRECORDED = frozenset(
    {
        "spots",
        "forecast",
        "forecast_meta",
        "timings",
        "overnight",
        "now",
        "rooms",
        "config",
        "diagnostics",
        "advice",
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for one configured setup."""
    coordinator: LaundryWeatherCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        RecommendationSensor(coordinator),
        AdviceSensor(coordinator),
        CoveredLineScoreSensor(coordinator),
        OpenLineScoreSensor(coordinator),
        BringInBySensor(coordinator),
        MoveOutsideAtSensor(coordinator),
        BestWindowSensor(coordinator),
    ]
    entities.extend(
        RoomScoreSensor(coordinator, room[CONF_ROOM_NAME])
        for room in coordinator.rooms
    )
    async_add_entities(entities)


class _ScoreSensor(LaundryWeatherEntity, SensorEntity):
    """A drying score in hPa, with its band named in the attributes."""

    _attr_native_unit_of_measurement = UnitOfPressure.HPA
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-percent"


class RoomScoreSensor(_ScoreSensor):
    """One per configured room — the reason this is not a single-room model."""

    def __init__(self, coordinator: LaundryWeatherCoordinator, name: str) -> None:
        # Keyed on the slug rather than the position, so renaming a room or
        # adding another one does not renumber everyone else's entity ids.
        super().__init__(coordinator, f"room_{slugify_room(name)}")
        self._room_name = name
        self._attr_translation_key = "room_score"
        self._attr_translation_placeholders = {"room": name}
        self._attr_name = f"{name} drying score"

    @property
    def native_value(self) -> float | None:
        for room in self.data.get("rooms", []):
            if room["name"] == self._room_name:
                return room.get("score")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        for room in self.data.get("rooms", []):
            if room["name"] == self._room_name:
                return {"band": room.get("band"), "room": self._room_name}
        return {"room": self._room_name}


class CoveredLineScoreSensor(_ScoreSensor):
    _attr_name = "Line under cover score"
    _attr_icon = "mdi:home-roof"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "covered_line")

    @property
    def native_value(self) -> float | None:
        return self.data.get("scores", {}).get("cover")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"band": self.data.get("bands", {}).get("cover")}


class OpenLineScoreSensor(_ScoreSensor):
    _attr_name = "Line in the sun score"
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "open_line")

    @property
    def native_value(self) -> float | None:
        return self.data.get("scores", {}).get("sun")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"band": self.data.get("bands", {}).get("sun")}


class RecommendationSensor(LaundryWeatherEntity, SensorEntity):
    """The verdict — and the card's single source of everything.

    The card configures one entity and reads the rest off these attributes, so
    renaming a room or adding one never breaks a dashboard.
    """

    _attr_name = "Recommendation"
    _attr_icon = "mdi:tshirt-crew"
    _unrecorded_attributes = UNRECORDED

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "recommendation")

    @property
    def native_value(self) -> str | None:
        return self.data.get("recommendation")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.data
        timings = dict(data.get("timings", {}))
        # Datetimes are serialised for the card; the timestamp sensors carry
        # the real objects.
        for key in ("move_outside_at", "bring_in_by", "sunset"):
            value = timings.get(key)
            if isinstance(value, datetime):
                timings[key] = value.isoformat()
        return {
            "recommended_score": data.get("recommendation_score"),
            "recommended_band": data.get("recommendation_band"),
            "best_indoor_room": data.get("best_indoor", {}).get("name"),
            "best_indoor_score": data.get("best_indoor", {}).get("score"),
            "cover_score": data.get("scores", {}).get("cover"),
            "sun_score": data.get("scores", {}).get("sun"),
            "good_drying_day": data.get("good_drying_day"),
            # Is anything drying outside right now? False after sunset, in rain,
            # or when the score is below the floor — which is when "bring in by"
            # has no deadline to give. Worth automating on: "tell me when
            # nothing is drying and the washing is still out".
            "drying_now": data.get("drying_now"),
            "currently_raining": data.get("now", {}).get("wet"),
            "washing_out": data.get("washing_out"),
            "advice": data.get("advice"),
            "spots": data.get("spots"),
            "rooms": data.get("rooms"),
            "forecast": data.get("forecast"),
            "forecast_meta": data.get("forecast_meta"),
            "timings": timings,
            "overnight": data.get("overnight"),
            "now": data.get("now"),
            "config": data.get("config"),
            "diagnostics": data.get("diagnostics"),
        }


class AdviceSensor(LaundryWeatherEntity, SensorEntity):
    """A sentence a non-developer can act on without reading anything else."""

    _attr_name = "Advice"
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "advice")

    @property
    def native_value(self) -> str | None:
        return self.data.get("advice")


class BringInBySensor(LaundryWeatherEntity, SensorEntity):
    """When washing left outside should come in. Always has a value."""

    _attr_name = "Bring in by"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "bring_in_by")

    @property
    def native_value(self) -> datetime | None:
        return self.data.get("timings", {}).get("bring_in_by")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"reason": self.data.get("timings", {}).get("bring_in_source")}


class MoveOutsideAtSensor(LaundryWeatherEntity, SensorEntity):
    """When taking it outside starts being worth it — or nothing, honestly."""

    _attr_name = "Move outside at"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "move_outside_at")

    @property
    def native_value(self) -> datetime | None:
        return self.data.get("timings", {}).get("move_outside_at")


class BestWindowSensor(LaundryWeatherEntity, SensorEntity):
    """The best stretch of the next two days, as a readable phrase."""

    _attr_name = "Best window"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: LaundryWeatherCoordinator) -> None:
        super().__init__(coordinator, "best_window")

    @property
    def native_value(self) -> str | None:
        window = self.data.get("timings", {}).get("best_window")
        return None if window is None else window.get("text")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        window = self.data.get("timings", {}).get("best_window") or {}
        return {
            "start": window.get("start"),
            "end": window.get("end"),
            "peak": window.get("peak"),
        }


def _as_local(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return dt_util.as_local(value)
    return None
