"""Config and options flow.

Every field carries helper text, because the person setting this up is not a
developer and "outdoor_humidity" tells them nothing they did not already know.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from . import calc
from .const import (
    CONF_ADD_ANOTHER,
    CONF_BAND_FAST,
    CONF_BAND_MODERATE,
    CONF_BAND_SLOW,
    CONF_BRING_IN_FLOOR,
    CONF_DEWPOINT,
    CONF_EXTERNAL_WASHING_ENTITY,
    CONF_FORECAST_HOURS,
    CONF_FORECAST_SUN_MODEL,
    CONF_KLINGON,
    CONF_NAME,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_OUTSIDE_MARGIN,
    CONF_RAIN_DETECTOR,
    CONF_RAIN_DRY_STATE,
    CONF_RAIN_RATE,
    CONF_REMOVE_ROOMS,
    CONF_ROOM_HUMIDITY,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMPERATURE,
    CONF_ROOMS,
    CONF_SHOW_MASCOT,
    CONF_SOLAR_PRESMOOTHED,
    CONF_SOLAR_RADIATION,
    CONF_SUN_COEFF,
    CONF_SUN_ELEVATION,
    CONF_SUNSET,
    CONF_WEATHER_ENTITY,
    CONF_WIND_GUST,
    CONF_WIND_SPEED,
    DEFAULT_FORECAST_HOURS,
    DEFAULT_KLINGON,
    DEFAULT_NAME,
    DEFAULT_RAIN_DRY_STATE,
    DEFAULT_SHOW_MASCOT,
    DOMAIN,
)

TEMPERATURE_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain=["sensor", "number", "input_number"])
)
HUMIDITY_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain=["sensor", "number", "input_number"])
)
ANY_SENSOR_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        domain=["sensor", "binary_sensor", "number", "input_number", "input_text"]
    )
)

STEP_OUTDOOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OUTDOOR_TEMPERATURE): TEMPERATURE_SELECTOR,
        vol.Required(CONF_OUTDOOR_HUMIDITY): HUMIDITY_SELECTOR,
        vol.Optional(CONF_DEWPOINT): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_WIND_SPEED): ANY_SENSOR_SELECTOR,
        vol.Optional(CONF_WIND_GUST): ANY_SENSOR_SELECTOR,
    }
)

STEP_SUN_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SOLAR_RADIATION): ANY_SENSOR_SELECTOR,
        vol.Optional(CONF_SOLAR_PRESMOOTHED, default=False): BooleanSelector(),
        vol.Optional(CONF_SUN_ELEVATION): ANY_SENSOR_SELECTOR,
        vol.Optional(CONF_SUNSET): EntitySelector(
            EntitySelectorConfig(domain=["sensor"])
        ),
    }
)

STEP_RAIN_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_RAIN_DETECTOR): ANY_SENSOR_SELECTOR,
        vol.Optional(
            CONF_RAIN_DRY_STATE, default=DEFAULT_RAIN_DRY_STATE
        ): TextSelector(),
        vol.Optional(CONF_RAIN_RATE): ANY_SENSOR_SELECTOR,
    }
)


def _room_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ROOM_NAME, default=defaults.get(CONF_ROOM_NAME, "")
            ): TextSelector(),
            vol.Required(
                CONF_ROOM_TEMPERATURE, default=defaults.get(CONF_ROOM_TEMPERATURE)
            ): TEMPERATURE_SELECTOR,
            vol.Required(
                CONF_ROOM_HUMIDITY, default=defaults.get(CONF_ROOM_HUMIDITY)
            ): HUMIDITY_SELECTOR,
            vol.Optional(CONF_ADD_ANOTHER, default=False): BooleanSelector(),
        }
    )


class LaundryWeatherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user through the sensors, then their drying rooms."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_outdoor()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
                    vol.Required(CONF_WEATHER_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain="weather")
                    ),
                }
            ),
        )

    async def async_step_outdoor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_sun()
        return self.async_show_form(step_id="outdoor", data_schema=STEP_OUTDOOR_SCHEMA)

    async def async_step_sun(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_rain()
        return self.async_show_form(step_id="sun", data_schema=STEP_SUN_SCHEMA)

    async def async_step_rain(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_room()
        return self.async_show_form(step_id="rain", data_schema=STEP_RAIN_SCHEMA)

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect drying rooms, looping until the user stops adding them."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_ROOM_NAME].strip()
            if not name:
                errors[CONF_ROOM_NAME] = "empty_room_name"
            elif any(
                room[CONF_ROOM_NAME].casefold() == name.casefold()
                for room in self._rooms
            ):
                errors[CONF_ROOM_NAME] = "duplicate_room_name"
            else:
                self._rooms.append(
                    {
                        CONF_ROOM_NAME: name,
                        CONF_ROOM_TEMPERATURE: user_input[CONF_ROOM_TEMPERATURE],
                        CONF_ROOM_HUMIDITY: user_input[CONF_ROOM_HUMIDITY],
                    }
                )
                if user_input.get(CONF_ADD_ANOTHER):
                    return await self.async_step_room()
                return self.async_create_entry(
                    title=self._data[CONF_NAME],
                    data=self._data,
                    options={CONF_ROOMS: self._rooms},
                )

        return self.async_show_form(
            step_id="room",
            data_schema=_room_schema(),
            errors=errors,
            description_placeholders={"count": str(len(self._rooms))},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LaundryWeatherOptionsFlow()


class LaundryWeatherOptionsFlow(OptionsFlow):
    """A menu, because these are four unrelated things to change."""

    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}

    @property
    def _options(self) -> dict[str, Any]:
        return dict(self.config_entry.options)

    @property
    def _rooms(self) -> list[dict[str, Any]]:
        return list(self._options.get(CONF_ROOMS, []))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["tuning", "display", "add_room", "remove_room", "sensors"],
        )

    async def async_step_tuning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            bands = (
                user_input[CONF_BAND_FAST],
                user_input[CONF_BAND_MODERATE],
                user_input[CONF_BAND_SLOW],
            )
            if not bands[0] > bands[1] > bands[2]:
                errors["base"] = "bands_not_descending"
            else:
                return self._save(user_input)

        current = self._options
        return self.async_show_form(
            step_id="tuning",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SUN_COEFF,
                        default=current.get(CONF_SUN_COEFF, calc.DEFAULT_SUN_COEFF),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=3, step=0.1, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_OUTSIDE_MARGIN,
                        default=current.get(CONF_OUTSIDE_MARGIN, calc.DEFAULT_MARGIN),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=1.5, step=0.05, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_BRING_IN_FLOOR,
                        default=current.get(
                            CONF_BRING_IN_FLOOR, calc.DEFAULT_BRING_IN_FLOOR
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=10, step=0.5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_BAND_FAST,
                        default=current.get(CONF_BAND_FAST, calc.DEFAULT_BANDS[0]),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=40, step=0.5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_BAND_MODERATE,
                        default=current.get(CONF_BAND_MODERATE, calc.DEFAULT_BANDS[1]),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=40, step=0.5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_BAND_SLOW,
                        default=current.get(CONF_BAND_SLOW, calc.DEFAULT_BANDS[2]),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0.5, max=40, step=0.5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_FORECAST_SUN_MODEL,
                        default=current.get(
                            CONF_FORECAST_SUN_MODEL, calc.FORECAST_MODEL_AUTO
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                calc.FORECAST_MODEL_AUTO,
                                calc.FORECAST_MODEL_UV,
                                calc.FORECAST_MODEL_CLOUD,
                                calc.FORECAST_MODEL_ELEVATION,
                            ],
                            translation_key="forecast_sun_model",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_display(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(user_input)

        current = self._options
        return self.async_show_form(
            step_id="display",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_KLINGON, default=current.get(CONF_KLINGON, DEFAULT_KLINGON)
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_SHOW_MASCOT,
                        default=current.get(CONF_SHOW_MASCOT, DEFAULT_SHOW_MASCOT),
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_FORECAST_HOURS,
                        default=current.get(
                            CONF_FORECAST_HOURS, DEFAULT_FORECAST_HOURS
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=6, max=48, step=1, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                    vol.Optional(
                        CONF_EXTERNAL_WASHING_ENTITY,
                        description={
                            "suggested_value": current.get(
                                CONF_EXTERNAL_WASHING_ENTITY
                            )
                        },
                    ): EntitySelector(
                        EntitySelectorConfig(domain=["input_boolean", "switch"])
                    ),
                }
            ),
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_ROOM_NAME].strip()
            rooms = self._rooms
            if not name:
                errors[CONF_ROOM_NAME] = "empty_room_name"
            elif any(r[CONF_ROOM_NAME].casefold() == name.casefold() for r in rooms):
                errors[CONF_ROOM_NAME] = "duplicate_room_name"
            else:
                rooms.append(
                    {
                        CONF_ROOM_NAME: name,
                        CONF_ROOM_TEMPERATURE: user_input[CONF_ROOM_TEMPERATURE],
                        CONF_ROOM_HUMIDITY: user_input[CONF_ROOM_HUMIDITY],
                    }
                )
                return self._save({CONF_ROOMS: rooms})

        return self.async_show_form(
            step_id="add_room", data_schema=_room_schema(), errors=errors
        )

    async def async_step_remove_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        rooms = self._rooms
        if user_input is not None:
            removing = set(user_input.get(CONF_REMOVE_ROOMS, []))
            kept = [r for r in rooms if r[CONF_ROOM_NAME] not in removing]
            return self._save({CONF_ROOMS: kept})

        return self.async_show_form(
            step_id="remove_room",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_REMOVE_ROOMS, default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=[r[CONF_ROOM_NAME] for r in rooms],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-pick the source sensors without starting over."""
        if user_input is not None:
            return self._save(user_input)

        current = {**self.config_entry.data, **self._options}
        schema = vol.Schema(
            {
                **STEP_OUTDOOR_SCHEMA.schema,
                **STEP_SUN_SCHEMA.schema,
                **STEP_RAIN_SCHEMA.schema,
            }
        )
        return self.async_show_form(
            step_id="sensors",
            data_schema=self.add_suggested_values_to_schema(schema, current),
        )

    def _save(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Merge into existing options — each menu edits its own slice."""
        merged = {**self._options, **user_input}
        return self.async_create_entry(title="", data=merged)
