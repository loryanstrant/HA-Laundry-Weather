"""The Laundry Weather integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later

from .blueprints_install import async_install_blueprints
from .const import (
    CARD_FILENAME,
    DOMAIN,
    INTEGRATION_VERSION,
    SERVICE_REFRESH,
    SERVICE_SET_WASHING_OUT,
    STATIC_URL_BASE,
)
from .coordinator import LaundryWeatherCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
]

CARD_URL = f"{STATIC_URL_BASE}/{CARD_FILENAME}"
CARD_RESOURCE_URL = f"{CARD_URL}?v={INTEGRATION_VERSION}"

#: Lovelace is often still loading when this entry is set up.
RESOURCE_RETRY_SECONDS = 5
RESOURCE_RETRY_LIMIT = 12

SET_WASHING_OUT_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Required("washing_out"): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Laundry Weather from a config entry."""
    await _async_register_static_path(hass)
    hass.async_create_task(_async_ensure_lovelace_resource(hass))
    # Same idea as the card: no second install step. Home Assistant only loads
    # blueprints from config/blueprints, so they have to be copied across.
    await async_install_blueprints(hass)

    coordinator = LaundryWeatherCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except Exception as err:  # noqa: BLE001 - surface as a retry, not a crash
        raise ConfigEntryNotReady(f"Could not read the drying sensors: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after an options change — rooms may have been added or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_static_path(hass: HomeAssistant) -> None:
    """Serve the card straight out of the integration directory.

    Deliberately not copied into `config/www/`: Home Assistant serves a
    pre-compressed `.gz` sibling from there in preference to the file itself,
    so replacing only the `.js` leaves the old card being served. Nothing is
    written into `www/`, so that trap cannot be sprung.
    """
    static_path = Path(__file__).parent / "www"
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL_BASE, str(static_path), False)]
        )
    except RuntimeError:
        # Already registered by another entry, or by a reload of this one.
        _LOGGER.debug("%s: static path %s already registered", DOMAIN, STATIC_URL_BASE)


async def _async_ensure_lovelace_resource(hass: HomeAssistant, attempt: int = 0) -> None:
    """Register the card as a Lovelace resource so nobody has to do it by hand.

    Retried rather than attempted once: Lovelace is frequently not loaded yet
    when this entry is set up, and giving up quietly at that point means the
    card is served but never registered, so every dashboard using it shows
    "Custom element doesn't exist". That is exactly what happened on the first
    run against DEV — the file was fetchable at its URL, and the resource list
    had no mention of it.
    """
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None) if lovelace else None
    if resources is None:
        if attempt < RESOURCE_RETRY_LIMIT:
            _LOGGER.debug(
                "%s: Lovelace not ready, retrying resource registration", DOMAIN
            )
            async_call_later(
                hass,
                RESOURCE_RETRY_SECONDS,
                lambda _now: hass.async_create_task(
                    _async_ensure_lovelace_resource(hass, attempt + 1)
                ),
            )
        else:
            _LOGGER.warning(
                "%s: could not register the card with Lovelace. Add it by hand "
                "under Settings > Dashboards > Resources:\n  url: %s\n  type: module",
                DOMAIN,
                CARD_RESOURCE_URL,
            )
        return

    # A dashboard mode other than "storage" is NOT a reason to give up. The
    # resource collection is storage-backed regardless of how the dashboards
    # themselves are defined, and bailing here is what left the card registered
    # nowhere on DEV: the file served fine, and the resource list had 32
    # entries belonging to other integrations and nothing of ours. Log what the
    # mode is, then carry on and let the attempt itself decide.
    mode = getattr(lovelace, "mode", None)
    if mode != "storage":
        _LOGGER.debug(
            "%s: Lovelace mode is %s; trying the resource manager anyway",
            DOMAIN,
            mode,
        )

    try:
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()

        for item in resources.async_items():
            if item.get("url", "").startswith(CARD_URL):
                if item["url"] != CARD_RESOURCE_URL:
                    await resources.async_update_item(
                        item["id"], {"url": CARD_RESOURCE_URL}
                    )
                return

        await resources.async_create_item(
            {"res_type": "module", "url": CARD_RESOURCE_URL}
        )
        _LOGGER.debug("%s: registered %s with Lovelace", DOMAIN, CARD_RESOURCE_URL)
    except Exception as err:  # noqa: BLE001 - a dashboard problem is not fatal
        _LOGGER.warning(
            "%s: could not register the card with Lovelace (%s). Add it by hand "
            "under Settings > Dashboards > Resources:\n  url: %s\n  type: module",
            DOMAIN,
            err,
            CARD_RESOURCE_URL,
        )


def _register_services(hass: HomeAssistant) -> None:
    """Register services once, however many setups exist."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    def _coordinators(call: ServiceCall) -> list[LaundryWeatherCoordinator]:
        entries = hass.data.get(DOMAIN, {})
        entry_id = call.data.get("entry_id")
        if entry_id:
            found = entries.get(entry_id)
            return [found] if found else []
        return list(entries.values())

    async def _handle_refresh(call: ServiceCall) -> None:
        for coordinator in _coordinators(call):
            await coordinator.async_request_refresh()

    async def _handle_set_washing_out(call: ServiceCall) -> None:
        for coordinator in _coordinators(call):
            await coordinator.async_set_washing_out(call.data["washing_out"])

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_WASHING_OUT,
        _handle_set_washing_out,
        schema=SET_WASHING_OUT_SCHEMA,
    )
