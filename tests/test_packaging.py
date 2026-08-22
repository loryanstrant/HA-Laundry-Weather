"""Packaging guards.

Three house failures have shipped before and each is cheap to catch here:
version drift between the manifest and a bundled card, option fields rendering
as raw keys because `translations/en.json` fell out of sync with
`strings.json`, and fields shipped with no explanatory text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COMPONENT = REPO / "custom_components" / "laundry_weather"
WWW = COMPONENT / "www"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _manifest() -> dict:
    return json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_version_is_semver() -> None:
    assert SEMVER.match(_manifest()["version"])


def test_manifest_domain_matches_folder() -> None:
    assert _manifest()["domain"] == COMPONENT.name


def test_hacs_filename_matches_domain() -> None:
    hacs = json.loads((REPO / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["filename"] == f"{_manifest()['domain']}.zip"
    # zip_release is what makes HACS install the release artifact rather than
    # the repo tree, so it has to agree with release.yaml producing that zip.
    assert hacs["zip_release"] is True


@pytest.mark.parametrize("card", sorted(WWW.glob("*.js")) or [None])
def test_card_version_matches_manifest(card: Path | None) -> None:
    """Every bundled card is versioned in lockstep with the integration.

    A user reading a card's console banner should never be troubleshooting a
    different version from the one HACS installed.
    """
    if card is None:
        pytest.skip("no bundled cards yet")
    found = re.search(r'CARD_VERSION\s*=\s*"([^"]+)"', card.read_text(encoding="utf-8"))
    assert found, f"{card.name} declares no CARD_VERSION"
    assert found.group(1) == _manifest()["version"], (
        f"{card.name} is at {found.group(1)}, manifest is at {_manifest()['version']}"
    )


def test_translations_match_strings() -> None:
    """`translations/en.json` must be a copy of `strings.json`.

    Custom integrations load config- and options-flow text from
    `translations/<lang>.json` at runtime, not from `strings.json`. Without the
    copy, every field renders as its raw key.
    """
    strings = COMPONENT / "strings.json"
    english = COMPONENT / "translations" / "en.json"
    if not strings.exists():
        pytest.skip("strings.json not written yet")
    assert english.exists(), "translations/en.json is missing"
    assert json.loads(strings.read_text(encoding="utf-8")) == json.loads(
        english.read_text(encoding="utf-8")
    )


def _walk_steps(node: dict):
    """Yield every step dict that declares a `data` block."""
    for value in node.values():
        if isinstance(value, dict):
            if "data" in value and isinstance(value["data"], dict):
                yield value
            yield from _walk_steps(value)


def test_every_field_has_helper_text() -> None:
    """Non-developers get no value from a bare field label."""
    strings = COMPONENT / "strings.json"
    if not strings.exists():
        pytest.skip("strings.json not written yet")
    data = json.loads(strings.read_text(encoding="utf-8"))
    missing: list[str] = []
    for step in _walk_steps(data):
        descriptions = step.get("data_description", {})
        for field in step["data"]:
            if field not in descriptions:
                missing.append(f"{step.get('title', '?')}.{field}")
    assert not missing, f"fields with no data_description: {missing}"
