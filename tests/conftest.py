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
TEST_TZ_NAME = "Australia/Melbourne"
TEST_TZ = ZoneInfo(TEST_TZ_NAME)

os.environ["TZ"] = TEST_TZ_NAME


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load this custom integration in every test."""
    return


@pytest.fixture
def local_tz() -> ZoneInfo:
    """Return the pinned local timezone."""
    return TEST_TZ


@pytest.fixture
def now() -> datetime:
    """A fixed local 'now' — mid-morning, so a full drying day lies ahead."""
    return datetime(2026, 8, 22, 9, 0, tzinfo=TEST_TZ)


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
