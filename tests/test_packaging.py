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


BUNDLED_BANNERS = (
    "worf-good.png",
    "worf-bad.png",
    "worf-good-klingon.png",
    "worf-bad-klingon.png",
)


@pytest.mark.parametrize("name", BUNDLED_BANNERS)
def test_bundled_banner_exists_and_is_small(name: str) -> None:
    """Banners are served on every card render, so weight matters.

    The source artwork is around a megabyte each; the shipped versions are
    trimmed, resized and quantised by `scripts/make_stickers.py`. If somebody
    drops a raw source file in here, this catches it.
    """
    banner = WWW / name
    assert banner.exists(), f"{name} is missing — run scripts/make_stickers.py"
    size = banner.stat().st_size
    assert size < 80 * 1024, f"{name} is {size // 1024} KB, which is too heavy"


def test_every_banner_has_a_klingon_variant() -> None:
    """The card picks a static file per state; a missing one renders broken."""
    for name in ("worf-good.png", "worf-bad.png"):
        variant = WWW / name.replace(".png", "-klingon.png")
        assert variant.exists(), f"no Klingon variant for {name}"


def test_the_card_registers_its_elements() -> None:
    """A card that defines no custom element silently does nothing."""
    source = (WWW / "laundry-weather-card.js").read_text(encoding="utf-8")
    assert 'customElements.define("laundry-weather-card"' in source
    assert 'customElements.define("laundry-weather-card-editor"' in source
    assert "window.customCards.push" in source


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


def test_manifest_keys_are_sorted_the_way_hassfest_wants() -> None:
    """`domain`, `name`, then everything else alphabetically.

    Home Assistant's hassfest action enforces this and fails the build over it.
    It shipped wrong once — `codeowners` sat before `after_dependencies` — and
    the only signal was a red CI run after the release had been cut.
    """
    keys = list(json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8")))
    assert keys[0] == "domain"
    assert keys[1] == "name"
    assert keys[2:] == sorted(keys[2:]), f"rest must be alphabetical, got {keys[2:]}"


@pytest.mark.parametrize(("name", "expected"), [("icon.png", 256), ("icon@2x.png", 512)])
def test_brand_icons_exist_at_the_size_hacs_expects(name: str, expected: int) -> None:
    """HACS fails validation without these, or a listing in the brands repo."""
    icon = COMPONENT / "brand" / name
    assert icon.exists(), f"{name} is missing — run scripts/make_brand_icons.py"

    # PNG dimensions live in the IHDR chunk, 16 bytes in. Read them directly
    # rather than adding an image library just for this.
    header = icon.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    assert (width, height) == (expected, expected), f"{name} is {width}x{height}"


def test_every_image_the_readme_points_at_exists() -> None:
    """A broken image is invisible until somebody opens the repo page.

    This shipped once: the README pointed at `_IMAGES/`, which is a session
    scratch directory that was never committed, so the only picture in the
    README rendered as a broken link on GitHub.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    referenced = set(re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", readme, re.S))
    referenced |= set(re.findall(r'<img[^>]+src="([^"]+)"', readme))

    local = [r for r in referenced if not r.startswith(("http://", "https://"))]
    assert local, "the README should show at least one screenshot"

    missing = [r for r in local if not (REPO / r).exists()]
    assert not missing, f"README references images that are not in the repo: {missing}"

    # Also keep them light — a README that takes a minute to load is its own bug.
    heavy = [
        f"{r} ({(REPO / r).stat().st_size // 1024} KB)"
        for r in local
        if (REPO / r).stat().st_size > 400 * 1024
    ]
    assert not heavy, f"README images are too heavy: {heavy}"
