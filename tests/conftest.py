"""Shared fixtures for the Laundry Weather tests."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

# Every hour-of-day decision in this integration is local-time: the overnight
# dew window is "18:00 to 08:00", the best-window label carries a weekday, and
# the card's hour ticks are local. A UTC-only test run would pass while the
# feature was wrong for anyone east of Greenwich, so the zone is pinned rather
# than inherited from the runner.
#
# ⚠ This pins the zone the *fixtures* construct datetimes in. It does not
# change the Home Assistant test instance, which stays on its own `US/Pacific`
# default — see the note on `TEST_NOW`.
TEST_TZ_NAME = "Australia/Melbourne"
TEST_TZ = ZoneInfo(TEST_TZ_NAME)

os.environ["TZ"] = TEST_TZ_NAME


# The moment every test runs at.
#
# ⚠ Read this in two timezones, because the suite runs in two. `TEST_TZ` below
# is what the *fixtures* build their datetimes in, but it is NOT the zone the
# Home Assistant test instance uses: `hass.config.time_zone` is
# `pytest-homeassistant-custom-component`'s own default, `US/Pacific`, with
# San Diego coordinates (32.87336, -117.22743). So `dt_util.now()` inside a
# test is Pacific, and every sunset the integration computes is San Diego's.
#
# In those terms this instant is 2026-08-21 16:00 PT, with sunset at 19:26 PT —
# about 3.5 hours of drying day still ahead, which is the shape the production
# snapshot these tests are built from was captured in.
TEST_NOW = datetime(2026, 8, 22, 9, 0, tzinfo=TEST_TZ)


@pytest.fixture(autouse=True)
def frozen_clock(freezer):
    """Pin the wall clock, for every test, before Home Assistant starts.

    Without this the suite's result depends on what time of day it runs.
    Several tests build their forecast relative to `dt_util.now()` and then
    assert on a judgement the integration makes about *the rest of today* —
    and `good_drying_day` is deliberately bounded at tonight's sunset
    (`calc.rest_of_today_peak`), so once "now" is near or past sunset in the
    instance's own Pacific zone there is correctly no drying day left and the
    sensor turns off. The assertions were written for a morning; from roughly
    half an hour before sunset onwards they fail, and the integration is right.

    This was not theoretical. The nightly cron landed around 17:30 PT, some
    37-40 minutes before a San Diego sunset, and passed 30 nights out of 31 on
    that margin alone; the one nightly that drifted to 18:12 PT (18 minutes of
    margin, 2026-10-04) failed, and so did every push made during an Australian
    afternoon. The margin was shrinking with the season, so it was going to
    stop passing outright.

    Freezing here rather than in each test means a test added later cannot
    quietly reintroduce the dependency on when the run happens to start.
    """
    freezer.move_to(TEST_NOW)
    return freezer


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load this custom integration in every test."""
    return


@pytest.fixture(autouse=True)
def disposable_config_dir(request, tmp_path):
    """Give each test its own config directory.

    `pytest-homeassistant-custom-component` points every test at one shared
    `testing_config/` inside site-packages. Setting the integration up installs
    its blueprints into it for real, so files survive the run and change what
    the next one sees. That already showed up here: a test that edits an
    installed blueprint made the test asserting the installed copy is pristine
    fail on the *second* run only.
    """
    if "hass" not in request.fixturenames:
        return
    hass = request.getfixturevalue("hass")
    hass.config.config_dir = str(tmp_path)


@pytest.fixture
def local_tz() -> ZoneInfo:
    """Return the pinned local timezone."""
    return TEST_TZ


@pytest.fixture
def now() -> datetime:
    """A fixed 'now' with a full drying day still ahead of it.

    The same moment the clock is frozen to, so a model test and an integration
    test are talking about the same instant. Model tests read it as 09:00
    Melbourne and pair it with the `sunset` fixture below; the integration
    sees the same instant as 16:00 PT. See `TEST_NOW`.
    """
    return TEST_NOW


@pytest.fixture
def sunset(now: datetime) -> datetime:
    """Sunset on the fixed day, matching the production sun2 reading."""
    return now.replace(hour=17, minute=51, second=22)


def make_hours(
    start: datetime,
    count: int,
    **overrides,
) -> list[dict]:
    """Build `count` consecutive hourly forecast dicts starting at `start`.

    Each keyword may be a scalar (applied to every hour) or a sequence (applied
    per hour, cycling if shorter than `count`). Returns the raw provider shape,
    so coordinator normalisation is exercised too.
    """
    base = {
        "temperature": 18.0,
        "humidity": 55.0,
        "wind_speed": 10.0,
        "uv_index": 3.0,
        "precipitation_probability": 0.0,
        "precipitation": 0.0,
    }
    hours: list[dict] = []
    for i in range(count):
        hour = dict(base)
        for key, value in overrides.items():
            if isinstance(value, (list, tuple)):
                hour[key] = value[i % len(value)]
            else:
                hour[key] = value
        hour["datetime"] = (start + timedelta(hours=i)).isoformat()
        hours.append(hour)
    return hours
