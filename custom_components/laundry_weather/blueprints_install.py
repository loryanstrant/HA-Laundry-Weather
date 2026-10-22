"""Copy the bundled automation blueprints into the user's blueprint folder.

Home Assistant only ever *loads* blueprints from `<config>/blueprints/` —
`blueprint/models.py` resolves the folder as
`hass.config.path("blueprints", domain)` — and offers no public API for an
integration to register one. So a blueprint shipped inside a custom component
is invisible until it is copied across, which is what this does, the same way
HACS does for blueprint repositories.

**Your copy is yours.** This records a SHA-256 of every file it installs, in
`config/.storage/laundry_weather_blueprints`. On the next start a destination
whose hash still matches the recorded one has not been touched, so it is safe
to replace with a newer bundled version; anything else is left exactly as it
is and merely logged. A file we have no record of — anyone who installed
before v0.4.1 — is also left alone, because an old shipped version and an
edited one are indistinguishable from the bytes.

This replaces an mtime comparison, which looked like the same guard and was
not: a HACS upgrade unzips the bundled files fresh, so the shipped file is
*always* newer than whatever is already in `config/blueprints/`, and an edited
copy was overwritten every time. Caught in review on hacs/default#10258; see
`DECISIONS.md`, 2026-10-22.

`HA-Personal-Hydration-Manager` still carries the original mtime version and
has the same bug.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

#: Matches the layout in the repo, and the folder the README's import badges
#: point at, so a hand-imported copy and an installed one land together.
_BLUEPRINT_SUBPATH = "automation/loryanstrant"
_DATA_INSTALLED = f"{DOMAIN}_blueprints_installed"

#: `config/.storage/laundry_weather_blueprints` — out of sight, and it survives
#: upgrades. Deliberately not a sidecar file in the blueprints folder, which is
#: the user's own space.
_STORE_KEY = f"{DOMAIN}_blueprints"
_STORE_VERSION = 1


def _digest(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _place(source: Path, destination: Path) -> None:
    """Write `source` to `destination` in one step, or not at all.

    A plain `copy2` truncates the destination and then writes it, so a failure
    part-way through (a full disk) leaves a half-written blueprint behind that
    matches neither the shipped file nor any record — which this module would
    then read forever as "the user edited it" and never repair. Copying to a
    temporary name in the same directory and renaming makes the swap atomic,
    so the destination is only ever the old file or the whole new one. The
    temporary name is not `*.yaml`, so Home Assistant will not try to load it
    if we die between the two steps.
    """
    temporary = destination.with_name(f".{source.name}.{DOMAIN}.tmp")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _install(
    source_dir: Path, dest_dir: Path, recorded: dict[str, str]
) -> tuple[list[str], list[str], dict[str, str]]:
    """Install the blueprints the user has not made their own.

    Returns `(copied, kept, installed)` — what was written, what was left
    alone because it differs from what we put there, and the hash record to
    persist.
    """
    copied: list[str] = []
    kept: list[str] = []
    installed = dict(recorded)

    if not source_dir.is_dir():
        return copied, kept, installed

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        _LOGGER.warning("%s: could not create %s: %s", DOMAIN, dest_dir, err)
        return copied, kept, installed

    for source in sorted(source_dir.glob("*.yaml")):
        destination = dest_dir / source.name
        try:
            source_digest = _digest(source)

            if not destination.exists():
                _place(source, destination)
                installed[source.name] = source_digest
                copied.append(source.name)
                continue

            destination_digest = _digest(destination)

            if destination_digest == source_digest:
                # Already the shipped version. Adopt it into the record so the
                # *next* upgrade can tell it was never edited.
                installed[source.name] = source_digest
                continue

            if recorded.get(source.name) == destination_digest:
                # Byte-for-byte what we last installed, so nobody has touched
                # it and replacing it loses nothing.
                _place(source, destination)
                installed[source.name] = source_digest
                copied.append(source.name)
                continue

            # Either the user edited it, or it predates the hash record. Both
            # are theirs to keep.
            kept.append(source.name)
        except OSError as err:
            # Per file, so one unwritable blueprint cannot take down setup.
            _LOGGER.warning(
                "%s: could not install blueprint %s: %s", DOMAIN, source.name, err
            )
    return copied, kept, installed


async def async_install_blueprints(hass: HomeAssistant) -> None:
    """Put the bundled blueprints where Home Assistant will find them.

    Nothing in here is allowed to fail setting the integration up. A blueprint
    that could not be written costs the user two notification automations they
    can still import by hand; the drying model, the sensors and the card have
    nothing to do with it.
    """
    # Claimed synchronously, before the first `await`. Nothing is
    # single-instance about this integration, and Home Assistant sets several
    # config entries of the same domain up concurrently — so a flag set after
    # an await leaves a window in which two entries both pass the check and
    # then race two executor threads over the same files, each able to hash a
    # file the other is half-way through writing.
    if hass.data.get(_DATA_INSTALLED):
        return
    hass.data[_DATA_INSTALLED] = True

    store: Store[dict[str, Any]] = Store(hass, _STORE_VERSION, _STORE_KEY)
    try:
        stored = await store.async_load() or {}
    except (HomeAssistantError, OSError, ValueError) as err:
        # A corrupt or unreadable record is not a reason to refuse to load.
        # Treat it as "no record", which is the conservative branch: every
        # existing file is left exactly as it is.
        _LOGGER.warning("%s: could not read the blueprint record: %s", DOMAIN, err)
        stored = {}
    recorded: dict[str, str] = dict(stored.get("installed", {}))

    source_dir = Path(__file__).parent / "blueprints" / _BLUEPRINT_SUBPATH
    dest_dir = Path(hass.config.path("blueprints", *_BLUEPRINT_SUBPATH.split("/")))

    copied, kept, installed = await hass.async_add_executor_job(
        _install, source_dir, dest_dir, recorded
    )

    if installed != recorded:
        try:
            await store.async_save({"installed": installed})
        except (HomeAssistantError, OSError) as err:
            # The files are already in place; only the record is lost. The
            # cost is that the next upgrade sees them as unrecorded and leaves
            # them alone, which is the safe direction to fail in.
            _LOGGER.warning("%s: could not save the blueprint record: %s", DOMAIN, err)

    if copied:
        _LOGGER.info(
            "%s: installed blueprints into %s: %s",
            DOMAIN,
            dest_dir,
            ", ".join(copied),
        )
    if kept:
        # Deliberately neutral about the cause: this covers both a copy the
        # user edited and a copy installed before v0.4.1, which carries no
        # record and so cannot be told apart from an edited one.
        _LOGGER.info(
            "%s: your copy of %s in %s differs from the version this release "
            "ships, so it was left untouched. To take the new version, delete "
            "yours under Settings > Automations & scenes > Blueprints and "
            "restart, or re-import it from the README.",
            DOMAIN,
            ", ".join(kept),
            dest_dir,
        )
    if not copied and not kept:
        _LOGGER.debug("%s: blueprints already up to date in %s", DOMAIN, dest_dir)
