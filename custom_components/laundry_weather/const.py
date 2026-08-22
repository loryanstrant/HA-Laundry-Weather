"""Constants for the Laundry Weather integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

DOMAIN: Final = "laundry_weather"

# Read once at import so the card cache-buster and the device sw_version always
# agree with the manifest, rather than drifting behind a hand-maintained copy.
INTEGRATION_VERSION: Final[str] = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)["version"]

# --- config entry keys: identity -------------------------------------------
CONF_NAME: Final = "name"
CONF_WEATHER_ENTITY: Final = "weather_entity"

# --- config entry keys: outdoor conditions ---------------------------------
CONF_OUTDOOR_TEMPERATURE: Final = "outdoor_temperature"
CONF_OUTDOOR_HUMIDITY: Final = "outdoor_humidity"
CONF_DEWPOINT: Final = "dewpoint"
CONF_WIND_SPEED: Final = "wind_speed"
CONF_WIND_GUST: Final = "wind_gust"

# --- config entry keys: sun ------------------------------------------------
CONF_SOLAR_RADIATION: Final = "solar_radiation"
CONF_SOLAR_PRESMOOTHED: Final = "solar_presmoothed"
CONF_SUN_ELEVATION: Final = "sun_elevation"
CONF_SUNSET: Final = "sunset"

# --- config entry keys: rain -----------------------------------------------
CONF_RAIN_DETECTOR: Final = "rain_detector"
CONF_RAIN_DRY_STATE: Final = "rain_dry_state"
CONF_RAIN_RATE: Final = "rain_rate"

# --- config entry keys: rooms ----------------------------------------------
CONF_ROOMS: Final = "rooms"
CONF_ROOM_NAME: Final = "room_name"
CONF_ROOM_TEMPERATURE: Final = "room_temperature"
CONF_ROOM_HUMIDITY: Final = "room_humidity"
CONF_ADD_ANOTHER: Final = "add_another"
CONF_REMOVE_ROOMS: Final = "remove_rooms"

# --- option keys: tuning ---------------------------------------------------
CONF_SUN_COEFF: Final = "sun_coeff"
CONF_OUTSIDE_MARGIN: Final = "outside_margin"
CONF_BRING_IN_FLOOR: Final = "bring_in_floor"
CONF_BAND_FAST: Final = "band_fast"
CONF_BAND_MODERATE: Final = "band_moderate"
CONF_BAND_SLOW: Final = "band_slow"
CONF_FORECAST_SUN_MODEL: Final = "forecast_sun_model"

# --- option keys: display --------------------------------------------------
CONF_KLINGON: Final = "klingon"
CONF_FORECAST_HOURS: Final = "forecast_hours"
CONF_SHOW_MASCOT: Final = "show_mascot"

# --- option keys: integration behaviour ------------------------------------
CONF_EXTERNAL_WASHING_ENTITY: Final = "external_washing_entity"

# --- defaults --------------------------------------------------------------
DEFAULT_NAME: Final = "Laundry Weather"
DEFAULT_RAIN_DRY_STATE: Final = "No"
DEFAULT_FORECAST_HOURS: Final = 24
DEFAULT_SHOW_MASCOT: Final = True
DEFAULT_KLINGON: Final = False

# Live conditions are all local state reads, so polling them is nearly free.
UPDATE_INTERVAL_SECONDS: Final = 120
# weather.get_forecasts is the only call that costs anything, and providers
# rarely refresh faster than hourly.
FORECAST_INTERVAL_SECONDS: Final = 900
# How soon to try again when the forecast could not be read at all. Short,
# because this is almost always a weather integration that had not finished
# starting yet.
FORECAST_RETRY_SECONDS: Final = 20
# Time constant for the internal solar smoothing EMA. Raw irradiance was
# observed swinging 528 -> 564 -> 426 -> 150 W/m2 inside one afternoon.
SOLAR_SMOOTHING_TAU_SECONDS: Final = 600

# --- attribute keys --------------------------------------------------------
ATTR_SPOTS: Final = "spots"
ATTR_FORECAST: Final = "forecast"
ATTR_FORECAST_META: Final = "forecast_meta"
ATTR_TIMINGS: Final = "timings"
ATTR_OVERNIGHT: Final = "overnight"
ATTR_NOW: Final = "now"
ATTR_CONFIG: Final = "config"
ATTR_DIAGNOSTICS: Final = "diagnostics"
ATTR_ADVICE: Final = "advice"
ATTR_ROOMS: Final = "rooms"

# --- frontend --------------------------------------------------------------
STATIC_URL_BASE: Final = "/laundry_weather_static"
CARD_FILENAME: Final = "laundry-weather-card.js"
MASCOT_GOOD_FILENAME: Final = "mascot-good.svg"
MASCOT_BAD_FILENAME: Final = "mascot-bad.svg"

# --- services --------------------------------------------------------------
SERVICE_REFRESH: Final = "refresh"
SERVICE_SET_WASHING_OUT: Final = "set_washing_out"
