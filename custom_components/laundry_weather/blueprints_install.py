"""Copy the bundled automation blueprints into the user's blueprint folder.

Home Assistant only ever *loads* blueprints from `<config>/blueprints/` —
`blueprint/models.py` resolves the folder as
`hass.config.path("blueprints", domain)` — and offers no public API for an
integration to register one. So a blueprint shipped inside a custom component
is invisible until it is copied across, which is what this does, the same way
HACS does for blueprint repositories.

Copies run off the event loop and only when the source is newer than the
destination (or the destination is missing), so this is a no-op on almost every
start. Overwriting a newer destination would silently discard edits a user made
to their own copy.

This mirrors `blueprints_install.py` in HA-Personal-Hydration-Manager, so the
two integrations behave the same way.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

#: Matches the layout in the repo, and the folder the README's import badges
#: point at, so a hand-imported copy and an installed one land together.
_BLUEPRINT_SUBPATH = "automation/loryanstrant"
_DATA_INSTALLED = f"{DOMAIN}_blueprints_installed"


def _copy_blueprints(source_dir: Path, dest_dir: Path) -> list[str]:
    """Copy newer or missing blueprints. Returns the names actually copied."""
    copied: list[str] = []
    if not source_dir.is_dir():
        return copied

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        _LOGGER.warning("%s: could not create %s: %s", DOMAIN, dest_dir, err)
        return copied

    for source in sorted(source_dir.glob("*.yaml")):
        destination = dest_dir / source.name
        try:
            if (
                not destination.exists()
                or source.stat().st_mtime > destination.stat().st_mtime
            ):
                shutil.copy2(source, destination)
                copied.append(source.name)
        except OSError as err:
            # Per file, so one unwritable blueprint cannot take down setup.
            _LOGGER.warning(
                "%s: could not install blueprint %s: %s", DOMAIN, source.name, err
            )
    return copied


async def async_install_blueprints(hass: HomeAssistant) -> None:
    """Put the bundled blueprints where Home Assistant will find them."""
    if hass.data.get(_DATA_INSTALLED):
        return

    source_dir = Path(__file__).parent / "blueprints" / _BLUEPRINT_SUBPATH
    dest_dir = Path(hass.config.path("blueprints", *_BLUEPRINT_SUBPATH.split("/")))

    copied = await hass.async_add_executor_job(_copy_blueprints, source_dir, dest_dir)

    hass.data[_DATA_INSTALLED] = True
    if copied:
        _LOGGER.info(
            "%s: installed blueprints into %s: %s",
            DOMAIN,
            dest_dir,
            ", ".join(copied),
        )
    else:
        _LOGGER.debug("%s: blueprints already up to date in %s", DOMAIN, dest_dir)
