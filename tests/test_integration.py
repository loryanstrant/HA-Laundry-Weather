"""Does it actually load, and does it produce the right entities?

These run a real Home Assistant instance from
`pytest-homeassistant-custom-component`, so they catch the things pure model
tests cannot: wiring, unit conversion off real state attributes, and whether
the card's attribute payload is actually there.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path

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


# --- the card's Lovelace registration ---------------------------------------


class _FakeResources:
    """Enough of Home Assistant's resource collection to assert against."""

    def __init__(self, items=None, loaded=True):
        self.items = list(items or [])
        self.loaded = loaded
        self.created = []
        self.updated = []

    async def async_load(self):
        self.loaded = True

    def async_items(self):
        return list(self.items)

    async def async_create_item(self, data):
        self.created.append(data)
        return data

    async def async_update_item(self, item_id, data):
        self.updated.append((item_id, data))


class _FakeLovelace:
    def __init__(self, resources, mode):
        self.resources = resources
        self.mode = mode


@pytest.mark.parametrize("mode", ["storage", "yaml", None])
async def test_the_card_is_registered_whatever_the_dashboard_mode(
    hass: HomeAssistant, mode
) -> None:
    """A non-storage dashboard mode must not stop the card registering.

    This shipped broken: the code returned early unless the mode was exactly
    "storage", so on a real instance the card was served at its URL and
    registered nowhere, and every dashboard using it showed "Custom element
    doesn't exist". The resource collection is storage-backed regardless of how
    the dashboards themselves are defined.
    """
    from custom_components.laundry_weather import (
        CARD_RESOURCE_URL,
        _async_ensure_lovelace_resource,
    )

    resources = _FakeResources()
    hass.data["lovelace"] = _FakeLovelace(resources, mode)

    await _async_ensure_lovelace_resource(hass)

    assert resources.created == [
        {"res_type": "module", "url": CARD_RESOURCE_URL}
    ], f"card not registered with dashboard mode {mode!r}"


async def test_registering_twice_does_not_duplicate_the_resource(
    hass: HomeAssistant,
) -> None:
    from custom_components.laundry_weather import (
        CARD_RESOURCE_URL,
        _async_ensure_lovelace_resource,
    )

    resources = _FakeResources(
        items=[{"id": "abc", "url": CARD_RESOURCE_URL, "type": "module"}]
    )
    hass.data["lovelace"] = _FakeLovelace(resources, "storage")

    await _async_ensure_lovelace_resource(hass)

    assert resources.created == []
    assert resources.updated == []


async def test_an_older_version_of_the_resource_is_updated_in_place(
    hass: HomeAssistant,
) -> None:
    """The ?v= cache buster changes every release; the entry must follow."""
    from custom_components.laundry_weather import (
        CARD_URL,
        CARD_RESOURCE_URL,
        _async_ensure_lovelace_resource,
    )

    resources = _FakeResources(
        items=[{"id": "abc", "url": f"{CARD_URL}?v=0.0.1", "type": "module"}]
    )
    hass.data["lovelace"] = _FakeLovelace(resources, "storage")

    await _async_ensure_lovelace_resource(hass)

    assert resources.created == []
    assert resources.updated == [("abc", {"url": CARD_RESOURCE_URL})]


async def test_a_broken_resource_manager_is_survivable(
    hass: HomeAssistant, caplog
) -> None:
    """A dashboard problem must never stop the integration loading."""
    from custom_components.laundry_weather import _async_ensure_lovelace_resource

    class _Exploding(_FakeResources):
        async def async_create_item(self, data):
            raise RuntimeError("resource store is read-only")

    hass.data["lovelace"] = _FakeLovelace(_Exploding(), "storage")

    await _async_ensure_lovelace_resource(hass)

    assert "Add it by hand" in caplog.text


# --- the blueprints -----------------------------------------------------------


@pytest.fixture
def blueprint_config_dir(hass: HomeAssistant):
    """Where the blueprints should land, inside this test's own config dir.

    The config directory is made disposable per test in `conftest.py`, so an
    install here cannot leak into the next run.
    """
    return Path(hass.config.path("blueprints", "automation", "loryanstrant"))


SHIPPED_BLUEPRINTS = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "laundry_weather"
    / "blueprints"
    / "automation"
    / "loryanstrant"
)


async def test_the_blueprints_install_themselves(
    hass: HomeAssistant, blueprint_config_dir, loaded_entry: MockConfigEntry
) -> None:
    """Setting the integration up must be the only step.

    Home Assistant loads blueprints from `config/blueprints/<domain>/` and
    nowhere else, so a blueprint shipped inside a custom component is invisible
    until something copies it there. Nothing warns about this — the user simply
    never sees them.
    """
    shipped = sorted(SHIPPED_BLUEPRINTS.glob("*.yaml"))
    assert shipped, "nothing is bundled to install"

    for source in shipped:
        landed = blueprint_config_dir / source.name
        assert landed.exists(), f"{source.name} was never installed"
        assert landed.read_bytes() == source.read_bytes()


async def test_an_edited_copy_is_not_clobbered(
    hass: HomeAssistant, blueprint_config_dir, loaded_entry: MockConfigEntry
) -> None:
    """Somebody's own tweak survives a restart.

    Copying unconditionally would silently throw away edits every time Home
    Assistant restarted, which is the kind of loss nobody thinks to look for.

    ⚠ This test was never sufficient on its own, and said so nowhere. It edits
    the destination *after* the install, which leaves the destination newer
    than the bundled file — so the old mtime guard passed it while still
    overwriting edits on a real upgrade, where the unzipped file is always the
    newer one. `test_an_upgrade_does_not_clobber_an_edited_copy` below is the
    one that actually covers that, and it is the case HACS review caught.
    """
    from custom_components.laundry_weather.blueprints_install import (
        _DATA_INSTALLED,
        async_install_blueprints,
    )

    mine = next(blueprint_config_dir.glob("*.yaml"))
    mine.write_text("# my own version\n", encoding="utf-8")

    # Pretend this is a fresh start, so the copy is genuinely re-attempted.
    hass.data.pop(_DATA_INSTALLED, None)
    await async_install_blueprints(hass)

    assert mine.read_text(encoding="utf-8") == "# my own version\n"


def _bundle(tmp_path: Path, body: str) -> tuple[Path, Path, Path]:
    """A one-file bundled blueprint folder and the config folder it installs to."""
    source_dir = tmp_path / "bundled"
    source_dir.mkdir(exist_ok=True)
    source = source_dir / "bring_it_in.yaml"
    source.write_text(body, encoding="utf-8")
    return source_dir, source, tmp_path / "config_blueprints"


def _age_backwards(path: Path) -> None:
    """Make a file look old, the way an upgrade makes the shipped one look new.

    HACS unzips the component on every upgrade, so the bundled blueprint
    always carries a fresh mtime and the destination always looks older. That
    is precisely the ordering the old guard got wrong.
    """
    stamp = time.time() - 86400
    os.utime(path, (stamp, stamp))


def test_an_upgrade_does_not_clobber_an_edited_copy(tmp_path: Path) -> None:
    """The failure HACS review caught — an upgrade eating the user's edits.

    hacs/default#10258: the installer compared mtimes, and on upgrade the
    freshly unzipped file is always newer, so an edited copy was replaced
    without warning. Reproduced here by editing the destination and *then*
    shipping a newer bundled version, which is the real-world order.
    """
    from custom_components.laundry_weather.blueprints_install import _install

    source_dir, source, dest_dir = _bundle(tmp_path, "shipped v1\n")
    copied, kept, recorded = _install(source_dir, dest_dir, {})
    assert copied == ["bring_it_in.yaml"]

    # The user tailors their copy, then time passes.
    destination = dest_dir / "bring_it_in.yaml"
    destination.write_text("my own version\n", encoding="utf-8")
    _age_backwards(destination)

    # v0.4.2 ships an improved blueprint and HACS unzips it: newer mtime,
    # different bytes. Under the old guard this overwrote the edit.
    source.write_text("shipped v2\n", encoding="utf-8")

    copied, kept, recorded = _install(source_dir, dest_dir, recorded)

    assert copied == []
    assert kept == ["bring_it_in.yaml"]
    assert destination.read_text(encoding="utf-8") == "my own version\n"


def test_an_untouched_copy_is_upgraded(tmp_path: Path) -> None:
    """Not overwriting edits must not mean never improving anything.

    If the installed file is byte-for-byte what we put there, nobody has
    anything to lose by replacing it.
    """
    from custom_components.laundry_weather.blueprints_install import _install

    source_dir, source, dest_dir = _bundle(tmp_path, "shipped v1\n")
    _, _, recorded = _install(source_dir, dest_dir, {})

    destination = dest_dir / "bring_it_in.yaml"
    _age_backwards(destination)
    source.write_text("shipped v2\n", encoding="utf-8")

    copied, kept, recorded = _install(source_dir, dest_dir, recorded)

    assert copied == ["bring_it_in.yaml"]
    assert kept == []
    assert destination.read_text(encoding="utf-8") == "shipped v2\n"
    assert recorded["bring_it_in.yaml"] == hashlib.sha256(b"shipped v2\n").hexdigest()


def test_a_copy_we_have_no_record_of_is_left_alone(tmp_path: Path) -> None:
    """Anyone who installed before v0.4.1 keeps what they have.

    Without a recorded hash, an old shipped version and an edited one are the
    same bytes-differ case, so the only safe answer is to touch neither.
    """
    from custom_components.laundry_weather.blueprints_install import _install

    source_dir, _, dest_dir = _bundle(tmp_path, "shipped v2\n")
    dest_dir.mkdir(parents=True)
    destination = dest_dir / "bring_it_in.yaml"
    destination.write_text("whatever they already had\n", encoding="utf-8")
    _age_backwards(destination)

    copied, kept, recorded = _install(source_dir, dest_dir, {})

    assert copied == []
    assert kept == ["bring_it_in.yaml"]
    assert "bring_it_in.yaml" not in recorded
    assert destination.read_text(encoding="utf-8") == "whatever they already had\n"


def test_an_identical_copy_is_adopted_into_the_record(tmp_path: Path) -> None:
    """A file that already matches what we ship becomes trackable.

    Someone who imported by URL, or who installed before v0.4.1 and never
    edited, ends up with the shipped bytes on disk. Recording them means the
    upgrade *after* this one can recognise the file as untouched.
    """
    from custom_components.laundry_weather.blueprints_install import _install

    source_dir, _, dest_dir = _bundle(tmp_path, "shipped v1\n")
    dest_dir.mkdir(parents=True)
    (dest_dir / "bring_it_in.yaml").write_text("shipped v1\n", encoding="utf-8")

    copied, kept, recorded = _install(source_dir, dest_dir, {})

    assert copied == []
    assert kept == []
    assert recorded["bring_it_in.yaml"] == hashlib.sha256(b"shipped v1\n").hexdigest()


async def test_what_we_installed_is_recorded_where_it_survives_a_restart(
    hass: HomeAssistant, blueprint_config_dir, loaded_entry: MockConfigEntry
) -> None:
    """The record lives in Home Assistant's store, not in memory.

    An in-memory record would be empty on every start, which turns every
    upgrade back into the unrecorded case and quietly strands everybody on
    their current blueprint.
    """
    from homeassistant.helpers.storage import Store

    from custom_components.laundry_weather.blueprints_install import (
        _STORE_KEY,
        _STORE_VERSION,
    )

    stored = await Store(hass, _STORE_VERSION, _STORE_KEY).async_load()
    assert stored and stored["installed"], "nothing was recorded"

    for name, digest in stored["installed"].items():
        landed = blueprint_config_dir / name
        assert landed.exists(), f"{name} is recorded but not installed"
        assert hashlib.sha256(landed.read_bytes()).hexdigest() == digest


def test_a_failed_copy_leaves_no_half_written_blueprint(tmp_path: Path) -> None:
    """A disk that fills mid-copy must not strand a corrupt file.

    `copy2` truncates and then writes, so a failure part-way leaves a
    destination matching neither the shipped file nor any record — which this
    module would read as a user edit forever and never repair. The write goes
    via a temporary name and a rename instead.
    """
    from custom_components.laundry_weather.blueprints_install import _install

    source_dir, _, dest_dir = _bundle(tmp_path, "shipped v1\n")
    dest_dir.mkdir(parents=True)
    destination = dest_dir / "bring_it_in.yaml"
    destination.write_text("the version already installed\n", encoding="utf-8")

    def _die_mid_write(src, dst, **kwargs):
        Path(dst).write_text("half a f", encoding="utf-8")
        raise OSError("no space left on device")

    already = hashlib.sha256(b"the version already installed\n").hexdigest()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("shutil.copy2", _die_mid_write)
        copied, kept, recorded = _install(
            source_dir, dest_dir, {"bring_it_in.yaml": already}
        )

    assert copied == []
    assert destination.read_text(encoding="utf-8") == "the version already installed\n"
    assert not list(dest_dir.glob(".*tmp")), "a temporary file was left behind"


async def test_a_broken_record_does_not_break_the_integration(
    hass: HomeAssistant, blueprint_config_dir, caplog
) -> None:
    """Blueprints are a side feature; the drying model is not.

    An unreadable `.storage` file must cost the blueprint update, not every
    sensor in the integration.
    """
    from homeassistant.helpers.storage import Store

    from custom_components.laundry_weather.blueprints_install import (
        async_install_blueprints,
    )

    async def _corrupt(self):
        raise ValueError("not valid JSON")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Store, "async_load", _corrupt)
        await async_install_blueprints(hass)

    assert "could not read the blueprint record" in caplog.text
    # And with no record it takes the conservative branch: still installs what
    # is missing, because there is nothing there to lose.
    assert list(blueprint_config_dir.glob("*.yaml"))


async def test_two_config_entries_cannot_race_each_other(hass: HomeAssistant) -> None:
    """Nothing makes this integration single-instance.

    Home Assistant sets config entries of the same domain up concurrently. A
    once-per-run flag set *after* an await leaves a window where both entries
    run the install in separate executor threads over the same files, each
    able to hash a file the other is half-way through writing.
    """
    import asyncio

    from custom_components.laundry_weather import blueprints_install

    calls: list[int] = []

    def _record(source_dir, dest_dir, recorded):
        calls.append(1)
        return [], [], dict(recorded)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(blueprints_install, "_install", _record)
        await asyncio.gather(
            blueprints_install.async_install_blueprints(hass),
            blueprints_install.async_install_blueprints(hass),
        )

    assert len(calls) == 1, "both entries installed at once"


async def test_an_unwritable_blueprint_folder_does_not_break_setup(
    hass: HomeAssistant, blueprint_config_dir, caplog
) -> None:
    """A read-only config directory must cost the notifications, not the integration."""
    from custom_components.laundry_weather.blueprints_install import (
        async_install_blueprints,
    )

    def _explode(*args, **kwargs):
        raise OSError("read-only file system")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("shutil.copy2", _explode)
        await async_install_blueprints(hass)

    assert "could not install blueprint" in caplog.text


async def test_the_card_gets_an_advice_template_it_can_reformat(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The sentence reaches the card with its times still substitutable.

    12h-vs-24h is `hass.locale.time_format`, a per-user frontend setting that
    never reaches Python, so the backend physically cannot render this sentence
    correctly for a 12-hour dashboard. It ships the wording; the card fills in
    the clock.
    """
    attrs = hass.states.get("sensor.laundry_weather_recommendation").attributes

    template = attrs["advice_template"]
    assert "{bring_by}" in template
    assert not re.search(r"\d{1,2}:\d{2}", template), (
        f"a real clock time survived into the template: {template}"
    )

    # And it still says the same thing as the entity everything else reads.
    timings = attrs["timings"]
    filled = (
        template.replace("{bring_by}", timings["bring_in_by"][11:16])
        .replace("{move_at}", (timings["move_outside_at"] or "")[11:16])
        .replace("{window}", (timings["best_window"] or {}).get("text", ""))
    )
    assert filled == attrs["advice"]


async def test_the_headline_is_about_the_day_not_the_minute(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """A cold still morning with a good afternoon is a good day to dry.

    The production snapshot these tests run on is exactly that shape, and it
    reported "not a good day" while telling the user to move the washing out at
    noon.
    """
    attrs = hass.states.get("sensor.laundry_weather_recommendation").attributes
    peak = attrs["timings"]["best_window"]["peak"]
    sun = attrs["sun_score"]
    cover = attrs["cover_score"]

    # The shape that made this wrong: neither outdoor spot is anywhere near the
    # Moderate band right now, and the day still peaks well past it.
    assert max(sun, cover) < 6.0, "fixture no longer reproduces the bug"
    assert peak >= 6.0, "fixture no longer has a good day in it"

    assert hass.states.get("binary_sensor.laundry_weather_good_drying_day").state == "on"
