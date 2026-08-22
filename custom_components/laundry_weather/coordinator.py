"""Reads the world, hands plain numbers to the model.

Everything that touches Home Assistant lives here: state reads, unit
conversion, solar smoothing and the forecast fetch. `calc` gets numbers in
known units and returns answers; keeping that boundary sharp is what makes the
model testable without an instance.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.weather import (
    ATTR_FORECAST_CLOUD_COVERAGE,
    ATTR_FORECAST_HUMIDITY,
    ATTR_FORECAST_NATIVE_TEMP,
    ATTR_FORECAST_NATIVE_WIND_SPEED,
    ATTR_FORECAST_PRECIPITATION,
    ATTR_FORECAST_PRECIPITATION_PROBABILITY,
    ATTR_FORECAST_TEMP,
    ATTR_FORECAST_TIME,
    ATTR_FORECAST_UV_INDEX,
    ATTR_FORECAST_WIND_SPEED,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.sun import get_astral_event_date, get_astral_event_next
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import calc
from .const import (
    CONF_BAND_FAST,
    CONF_BAND_MODERATE,
    CONF_BAND_SLOW,
    CONF_BRING_IN_FLOOR,
    CONF_DEWPOINT,
    CONF_EXTERNAL_WASHING_ENTITY,
    CONF_FORECAST_SUN_MODEL,
    CONF_KLINGON,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_OUTSIDE_MARGIN,
    CONF_RAIN_DETECTOR,
    CONF_RAIN_DRY_STATE,
    CONF_RAIN_RATE,
    CONF_ROOM_HUMIDITY,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMPERATURE,
    CONF_ROOMS,
    CONF_SOLAR_PRESMOOTHED,
    CONF_SOLAR_RADIATION,
    CONF_SUN_COEFF,
    CONF_SUN_ELEVATION,
    CONF_SUNSET,
    CONF_WEATHER_ENTITY,
    CONF_WIND_GUST,
    CONF_WIND_SPEED,
    DEFAULT_KLINGON,
    DEFAULT_RAIN_DRY_STATE,
    DOMAIN,
    FORECAST_INTERVAL_SECONDS,
    FORECAST_RETRY_SECONDS,
    SOLAR_SMOOTHING_TAU_SECONDS,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

INVALID_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN, "", "none", "None"}

#: Wind speeds arrive in whatever the source sensor reports; the model wants
#: km/h. Values are multipliers onto km/h.
WIND_TO_KMH: dict[str, float] = {
    UnitOfSpeed.KILOMETERS_PER_HOUR: 1.0,
    UnitOfSpeed.METERS_PER_SECOND: 3.6,
    UnitOfSpeed.MILES_PER_HOUR: 1.609344,
    UnitOfSpeed.KNOTS: 1.852,
    UnitOfSpeed.FEET_PER_SECOND: 1.09728,
}

#: Sun elevation sensors occasionally report radians. Anything outside this
#: range is not degrees, whatever the sensor claims.
ELEVATION_RANGE = (-90.0, 90.0)


def slugify_room(name: str) -> str:
    """Stable key for a room, so renaming it does not orphan its entity."""
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


class LaundryWeatherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the configured sensors and derives every answer."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        self._solar_ema: float | None = None
        self._solar_ema_at: datetime | None = None
        self._forecast_cache: list[calc.ForecastHour] = []
        self._forecast_fetched_at: datetime | None = None
        self._forecast_stale = False
        self._washing_out = False
        self._missing: list[str] = []
        self._retry_unsub: Callable[[], None] | None = None

    # --- configuration -----------------------------------------------------

    @property
    def settings(self) -> dict[str, Any]:
        """Entry data overlaid with options, which is what the user edits."""
        return {**self.entry.data, **self.entry.options}

    @property
    def tuning(self) -> calc.Tuning:
        settings = self.settings
        return calc.Tuning(
            sun_coeff=float(settings.get(CONF_SUN_COEFF, calc.DEFAULT_SUN_COEFF)),
            margin=float(settings.get(CONF_OUTSIDE_MARGIN, calc.DEFAULT_MARGIN)),
            bring_in_floor=float(
                settings.get(CONF_BRING_IN_FLOOR, calc.DEFAULT_BRING_IN_FLOOR)
            ),
            bands=(
                float(settings.get(CONF_BAND_FAST, calc.DEFAULT_BANDS[0])),
                float(settings.get(CONF_BAND_MODERATE, calc.DEFAULT_BANDS[1])),
                float(settings.get(CONF_BAND_SLOW, calc.DEFAULT_BANDS[2])),
            ),
            forecast_sun_model=settings.get(
                CONF_FORECAST_SUN_MODEL, calc.FORECAST_MODEL_AUTO
            ),
        )

    @property
    def rooms(self) -> list[dict[str, str]]:
        """Configured drying rooms. More than one is the normal case."""
        return list(self.settings.get(CONF_ROOMS, []))

    @property
    def washing_out(self) -> bool:
        external = self.settings.get(CONF_EXTERNAL_WASHING_ENTITY)
        if external:
            state = self.hass.states.get(external)
            if state is not None:
                return state.state == "on"
        return self._washing_out

    async def async_set_washing_out(self, value: bool) -> None:
        """Record whether there is washing on the line and re-derive advice."""
        external = self.settings.get(CONF_EXTERNAL_WASHING_ENTITY)
        if external:
            await self.hass.services.async_call(
                external.split(".")[0],
                "turn_on" if value else "turn_off",
                {"entity_id": external},
                blocking=True,
            )
        self._washing_out = value
        await self.async_request_refresh()

    # --- state reading -----------------------------------------------------

    def _raw_state(self, entity_id: str | None) -> Any | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in INVALID_STATES:
            self._missing.append(entity_id)
            return None
        return state

    def _number(self, entity_id: str | None) -> float | None:
        """Read a numeric state, or None. Never coerce a bad reading to zero.

        A sensor reporting 'unavailable' is not reporting zero, and treating it
        as zero would quietly claim the air is saturated or the wind still.
        """
        state = self._raw_state(entity_id)
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            self._missing.append(entity_id or "?")
            return None

    def _temperature_c(self, entity_id: str | None) -> float | None:
        state = self._raw_state(entity_id)
        if state is None:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            self._missing.append(entity_id or "?")
            return None
        if state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfTemperature.FAHRENHEIT:
            return (value - 32.0) * 5.0 / 9.0
        return value

    def _wind_kmh(self, entity_id: str | None) -> float | None:
        state = self._raw_state(entity_id)
        if state is None:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            self._missing.append(entity_id or "?")
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        return value * WIND_TO_KMH.get(unit, 1.0)

    def _elevation(self, now: datetime) -> float | None:
        """Sun elevation, from the configured sensor or Home Assistant itself.

        Most people should use HA's own sun tracker; the override exists for
        setups that already have a more precise source.
        """
        configured = self.settings.get(CONF_SUN_ELEVATION)
        if configured:
            value = self._number(configured)
            if value is not None and ELEVATION_RANGE[0] <= value <= ELEVATION_RANGE[1]:
                return value
            if value is not None:
                _LOGGER.warning(
                    "%s: %s reported %s, which is not degrees of elevation; "
                    "falling back to Home Assistant's sun tracker",
                    DOMAIN,
                    configured,
                    value,
                )
        sun = self.hass.states.get("sun.sun")
        if sun is not None:
            elevation = sun.attributes.get("elevation")
            if elevation is not None:
                return float(elevation)
        return None

    def _sunset(self, now: datetime) -> datetime:
        """Today's sunset if it is still ahead, otherwise the next one."""
        configured = self.settings.get(CONF_SUNSET)
        if configured:
            state = self._raw_state(configured)
            if state is not None:
                parsed = dt_util.parse_datetime(state.state)
                if parsed is not None:
                    return dt_util.as_local(parsed)

        today = get_astral_event_date(self.hass, "sunset", now)
        if today is not None and dt_util.as_local(today) > now:
            return dt_util.as_local(today)
        return dt_util.as_local(get_astral_event_next(self.hass, "sunset", now))

    def _smoothed_solar(self, raw: float | None, now: datetime) -> float | None:
        """Damp the noisiest input in the model.

        Raw irradiance was observed swinging 528 -> 564 -> 426 -> 150 W/m2
        inside one afternoon as cloud crossed. That term multiplies the sun
        factor between 1.0 and 2.2, so unsmoothed it flips the recommendation
        every few minutes.

        A time-constant EMA rather than a fixed-weight one, because the
        coordinator's tick is not guaranteed regular — a missed update should
        weight the next sample more, not less.
        """
        if raw is None:
            return self._solar_ema
        if self.settings.get(CONF_SOLAR_PRESMOOTHED):
            return raw
        if self._solar_ema is None or self._solar_ema_at is None:
            self._solar_ema = raw
            self._solar_ema_at = now
            return raw
        elapsed = max((now - self._solar_ema_at).total_seconds(), 0.0)
        weight = 1.0 - math.exp(-elapsed / SOLAR_SMOOTHING_TAU_SECONDS)
        self._solar_ema += weight * (raw - self._solar_ema)
        self._solar_ema_at = now
        return self._solar_ema

    # --- forecast ----------------------------------------------------------

    @staticmethod
    def _normalise_hour(raw: dict[str, Any]) -> calc.ForecastHour | None:
        """Map one provider forecast entry into the model's shape.

        Providers differ in which keys they populate, so both the native and
        the converted variants are accepted. An entry with no usable timestamp
        is dropped rather than guessed at.
        """
        stamp = raw.get(ATTR_FORECAST_TIME)
        if stamp is None:
            return None
        parsed = dt_util.parse_datetime(stamp) if isinstance(stamp, str) else stamp
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            # Not every provider stamps an offset — the Bureau of Meteorology
            # returns bare local times like "2026-08-22T17:00:00". Home
            # Assistant's own convention is that a naive datetime is local, so
            # it is read that way here. Rejecting them instead dropped every
            # hour of a BOM forecast on the floor and left the timings blank,
            # which is how this was found.
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

        def pick(*keys: str) -> float | None:
            for key in keys:
                value = raw.get(key)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
            return None

        return calc.ForecastHour(
            ts=dt_util.as_local(parsed),
            temp_c=pick(ATTR_FORECAST_NATIVE_TEMP, ATTR_FORECAST_TEMP),
            humidity=pick(ATTR_FORECAST_HUMIDITY),
            wind_kmh=pick(ATTR_FORECAST_NATIVE_WIND_SPEED, ATTR_FORECAST_WIND_SPEED),
            uv_index=pick(ATTR_FORECAST_UV_INDEX),
            cloud_pct=pick(ATTR_FORECAST_CLOUD_COVERAGE),
            precip_prob=pick(ATTR_FORECAST_PRECIPITATION_PROBABILITY),
            precip_mm=pick(ATTR_FORECAST_PRECIPITATION),
        )

    async def _async_forecast(self, now: datetime) -> list[calc.ForecastHour]:
        """Fetch the hourly forecast, throttled, with the last good series kept.

        A provider hiccup should cost the timing lines nothing — yesterday's
        forecast for this afternoon is far better than no forecast at all.
        """
        fresh_enough = (
            self._forecast_fetched_at is not None
            and (now - self._forecast_fetched_at).total_seconds()
            < FORECAST_INTERVAL_SECONDS
        )
        if fresh_enough:
            return self._forecast_cache

        weather_entity = self.settings.get(CONF_WEATHER_ENTITY)
        if not weather_entity:
            return self._forecast_cache

        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": weather_entity, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - any provider failure is survivable
            self._forecast_stale = bool(self._forecast_cache)
            _LOGGER.warning(
                "%s: could not read the hourly forecast from %s (%s); "
                "reusing the last one",
                DOMAIN,
                weather_entity,
                err,
            )
            self._schedule_retry()
            return self._forecast_cache

        entries = (response or {}).get(weather_entity, {}).get("forecast", [])
        hours = [h for h in (self._normalise_hour(e) for e in entries) if h is not None]
        if not hours:
            self._forecast_stale = bool(self._forecast_cache)
            self._missing.append(f"{weather_entity} (hourly forecast)")
            self._schedule_retry()
            return self._forecast_cache

        self._forecast_cache = hours
        self._forecast_fetched_at = now
        self._forecast_stale = False
        return hours

    def _schedule_retry(self) -> None:
        """Try again shortly when there is no forecast to fall back on.

        Weather integrations often finish starting a moment after this one, and
        `weather.get_forecasts` refuses an entity its service layer has not
        registered yet — measured at half a second late against a real Bureau
        of Meteorology feed. Waiting for the ordinary two-minute poll leaves
        every timing line blank for two minutes after each restart.

        Watching the entity's state does not help: the state object appears
        before the service will accept the entity, so the state is already
        there when this entry is set up and the wait ends too early. Retrying
        on a short timer needs no such assumption.
        """
        if self._forecast_cache or self._retry_unsub is not None:
            return

        async def _retry(_now) -> None:
            self._retry_unsub = None
            # Undebounced: async_request_refresh has a ten-second cooldown that
            # would swallow this.
            await self.async_refresh()

        self._retry_unsub = async_call_later(
            self.hass, FORECAST_RETRY_SECONDS, _retry
        )

    # --- the refresh -------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        self._missing = []
        settings = self.settings
        now = dt_util.now()

        temp_out = self._temperature_c(settings.get(CONF_OUTDOOR_TEMPERATURE))
        rh_out = self._number(settings.get(CONF_OUTDOOR_HUMIDITY))
        dewpoint = self._temperature_c(settings.get(CONF_DEWPOINT))
        wind = self._wind_kmh(settings.get(CONF_WIND_SPEED))
        gust = self._wind_kmh(settings.get(CONF_WIND_GUST))
        solar_raw = self._number(settings.get(CONF_SOLAR_RADIATION))
        solar = self._smoothed_solar(solar_raw, now)
        elevation = self._elevation(now)
        sunset = self._sunset(now)

        rain_state_entity = settings.get(CONF_RAIN_DETECTOR)
        rain_state = None
        if rain_state_entity:
            state = self._raw_state(rain_state_entity)
            rain_state = state.state if state is not None else None
        rain_rate = self._number(settings.get(CONF_RAIN_RATE))
        wet = calc.is_wet_now(
            rain_state,
            settings.get(CONF_RAIN_DRY_STATE, DEFAULT_RAIN_DRY_STATE),
            rain_rate,
        )

        vpd_out = (
            0.0
            if temp_out is None or rh_out is None
            else calc.vpd_hpa(temp_out, rh_out)
        )
        wn = calc.wind_norm(wind)
        sun_factor = calc.live_sun_factor(solar, elevation, self.tuning.sun_coeff)

        room_scores: dict[str, float] = {}
        room_detail: list[dict[str, Any]] = []
        for room in self.rooms:
            name = room[CONF_ROOM_NAME]
            room_temp = self._temperature_c(room.get(CONF_ROOM_TEMPERATURE))
            room_rh = self._number(room.get(CONF_ROOM_HUMIDITY))
            if room_temp is None or room_rh is None:
                # A room with a flat battery drops out of the ranking rather
                # than scoring zero and looking like the worst place to hang.
                room_detail.append(
                    {"name": name, "slug": slugify_room(name), "score": None}
                )
                continue
            score = calc.indoor_score(room_temp, room_rh)
            room_scores[name] = score
            room_detail.append(
                {
                    "name": name,
                    "slug": slugify_room(name),
                    "temperature": room_temp,
                    "humidity": room_rh,
                    "score": round(score, 2),
                    "band": calc.band(score, self.tuning.bands),
                }
            )

        # Sun elevation per forecast hour is what lets the cloud-cover model
        # work for providers that return no UV index. The astral observer is
        # resolved once per refresh rather than once per hour — doing it per
        # hour meant 48 lookups every two minutes, and on newer Home Assistant
        # it emitted 48 deprecation warnings a go, each inviting the user to
        # open a bug report.
        observer = _astral_observer(self.hass)
        hours = [
            replace(hour, elevation_deg=_solar_elevation(observer, hour.ts))
            for hour in await self._async_forecast(now)
        ]
        series, sun_model = calc.score_forecast(hours, now, self.tuning)

        assessment = calc.assess(
            rooms=room_scores,
            vpd_out=vpd_out,
            wn=wn,
            sun_factor=sun_factor,
            wet=wet,
            series=series,
            sun_model=sun_model,
            now=now,
            sunset=sunset,
            dewpoint_now=dewpoint,
            washing_out=self.washing_out,
            tuning=self.tuning,
        )

        return {
            "now": {
                "temp_out": temp_out,
                "rh_out": rh_out,
                "dewpoint": dewpoint,
                "vpd_out": round(vpd_out, 2),
                "wind_kmh": wind,
                "wind_gust_kmh": gust,
                "wind_norm": round(wn, 3),
                "solar_wm2": solar_raw,
                "solar_smoothed": None if solar is None else round(solar, 1),
                "elevation": elevation,
                "sky_fraction": round(calc.sky_fraction(solar, elevation), 3),
                "sun_gate": round(calc.sun_gate(elevation), 3),
                "sun_factor": round(sun_factor, 3),
                "rain_state": rain_state,
                "rain_rate": rain_rate,
                "wet": wet,
            },
            "rooms": room_detail,
            "scores": {
                "cover": round(assessment.cover, 2),
                "sun": round(assessment.sun, 2),
            },
            "bands": {
                "cover": calc.band(assessment.cover, self.tuning.bands),
                "sun": calc.band(assessment.sun, self.tuning.bands),
            },
            "best_indoor": {
                "name": assessment.best_room,
                "score": round(assessment.best_indoor, 2),
            },
            "spots": [
                {
                    "key": spot.key,
                    "name": spot.name,
                    "kind": spot.kind,
                    "score": round(spot.score, 2),
                    "band": spot.band,
                    "marks": spot.marks,
                    "rank": spot.rank,
                }
                for spot in assessment.spots
            ],
            "recommendation": assessment.recommendation,
            "recommendation_score": round(assessment.recommendation_score, 2),
            "recommendation_band": assessment.recommendation_band,
            "good_drying_day": assessment.good_day,
            "advice": assessment.advice,
            "timings": {
                "move_outside_at": assessment.move_at,
                "bring_in_by": assessment.bring_by,
                "bring_in_source": assessment.bring_by_source,
                "sunset": sunset,
                "best_window": (
                    None
                    if assessment.window is None
                    else {
                        "start": assessment.window.start.isoformat(),
                        "end": assessment.window.end.isoformat(),
                        "peak": round(assessment.window.peak, 1),
                        "text": assessment.window_text,
                    }
                ),
            },
            "overnight": {
                "rewet": assessment.dew,
                "min_temp": round(assessment.overnight_min, 1),
                "dewpoint_now": dewpoint,
            },
            "forecast": [
                {
                    "ts": hour.ts.isoformat(),
                    "hhmm": hour.hhmm,
                    "sun": round(hour.sun, 1),
                    "cov": round(hour.cov, 1),
                    "wet": hour.wet,
                }
                for hour in series
            ],
            "forecast_meta": {
                "count": len(series),
                "stale": self._forecast_stale,
                "fetched_at": (
                    None
                    if self._forecast_fetched_at is None
                    else self._forecast_fetched_at.isoformat()
                ),
                "source": settings.get(CONF_WEATHER_ENTITY),
                "sun_model": sun_model,
            },
            "washing_out": self.washing_out,
            "diagnostics": {
                "missing": sorted(set(self._missing)),
                "sun_scale_ratio": _sun_scale_ratio(sun_factor, series, self.tuning),
            },
            "config": {
                "sun_coeff": self.tuning.sun_coeff,
                "margin": self.tuning.margin,
                "bring_in_floor": self.tuning.bring_in_floor,
                "bands": list(self.tuning.bands),
                "klingon": bool(settings.get(CONF_KLINGON, DEFAULT_KLINGON)),
            },
        }


def _astral_observer(hass: HomeAssistant) -> Any | None:
    """Resolve whatever this Home Assistant version calls the sun observer.

    `get_astral_location` is deprecated from 2026 and removed in 2027.7, but
    `get_astral_observer` does not exist on older releases, so both are tried.
    """
    from homeassistant.helpers import sun as sun_helper

    getter = getattr(sun_helper, "get_astral_observer", None)
    if getter is not None:
        try:
            return getter(hass)
        except Exception:  # noqa: BLE001 - astral is a nicety, not a requirement
            return None
    try:
        return sun_helper.get_astral_location(hass)
    except Exception:  # noqa: BLE001
        return None


def _solar_elevation(observer: Any | None, when: datetime) -> float | None:
    """Sun elevation at a future time, for the cloud-cover forecast model."""
    if observer is None:
        return None
    try:
        if isinstance(observer, tuple):
            # Older API: (Location, elevation above sea level).
            location, elevation = observer
            return location.solar_elevation(when, elevation)
        import astral.sun

        return astral.sun.elevation(observer, when)
    except Exception:  # noqa: BLE001
        return None


def _sun_scale_ratio(
    live_factor: float, series: list[calc.ScoredHour], tuning: calc.Tuning
) -> float | None:
    """How far the live and forecast sun scales have drifted apart.

    Reported rather than corrected: the two models measure different things,
    and the point of surfacing the ratio is to make the divergence measurable
    over a season instead of arguing about it.
    """
    if not series:
        return None
    ceiling = 1.0 + tuning.sun_coeff / 2.0
    if ceiling <= 1.0:
        return None
    return round(live_factor / ceiling, 3)
