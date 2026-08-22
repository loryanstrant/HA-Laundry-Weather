#!/usr/bin/env python3
"""Render the brand icons Home Assistant and HACS look for.

Home Assistant reads an integration's own `brand/` folder — `loader.py`:

    def has_branding(self) -> bool:
        return "brand" in self._top_level_files

so this is what puts the icon beside "Laundry Weather" in the integrations
list. HACS checks the same folder during validation. Neither needs a pull
request to the home-assistant/brands repository.

`brand/logo-source.png` is the artwork as supplied; the two PNGs beside it are
generated from it and committed, so nobody has to run this to build the repo.
Re-run it after replacing the source:

    python scripts/make_brand_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

BRAND = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "laundry_weather"
    / "brand"
)
SOURCE = BRAND / "logo-source.png"
SIZES = {"icon.png": 256, "icon@2x.png": 512}


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing source artwork: {SOURCE}")

    art = Image.open(SOURCE).convert("RGBA")
    if art.width != art.height:
        # Home Assistant expects a square icon; centre-crop rather than squash.
        side = min(art.size)
        left = (art.width - side) // 2
        top = (art.height - side) // 2
        art = art.crop((left, top, left + side, top + side))

    print(f"source {SOURCE.name}: {art.width}x{art.height}")
    if art.width < max(SIZES.values()):
        # Say so rather than quietly upscaling and calling it done.
        print(
            f"note: source is smaller than {max(SIZES.values())}px, so "
            f"icon@2x.png is an upscale"
        )

    for name, size in SIZES.items():
        out = BRAND / name
        art.resize((size, size), Image.LANCZOS).save(out, "PNG", optimize=True)
        print(f"{name:<12} {size}x{size}  {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
