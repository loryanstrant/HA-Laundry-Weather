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

from PIL import Image, ImageFilter

BRAND = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "laundry_weather"
    / "brand"
)
SOURCE = BRAND / "logo-source.png"
SIZES = {"icon.png": 256, "icon@2x.png": 512}


def is_tile(pixel) -> bool:
    """Is this the saturated blue of the icon tile itself?

    Deliberately excludes two things that are *not* the artwork: the warm
    off-white the source was cut out of, and the tile's own pale-cyan outline
    ring. Both have a high red channel; the tile blue does not.
    """
    r, g, b = pixel[:3]
    return r < 150 and b > 150


def cut_out_tile(art: Image.Image) -> Image.Image:
    """Make everything around the tile transparent.

    The artwork was cut from a screenshot of a results grid, so it arrives with
    the grid's background filling the rounded corners *and* a pale outline ring
    around the tile. On a dark Home Assistant theme both show up as a white
    halo, which is what prompted this.

    Flooding inward from the four corners across everything that is not tile
    blue removes both in one pass. The white shirt and socks are safe: they sit
    inside the blue, so the flood cannot reach them.
    """
    art = art.convert("RGBA")
    width, height = art.size
    pixels = art.load()

    outside: set[tuple[int, int]] = set()
    stack = [
        corner
        for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
        if not is_tile(pixels[corner])
    ]
    outside.update(stack)
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in outside or is_tile(pixels[nx, ny]):
                continue
            outside.add((nx, ny))
            stack.append((nx, ny))

    mask = Image.new("L", (width, height), 255)
    mask_px = mask.load()
    for x, y in outside:
        mask_px[x, y] = 0
    # A hair of feathering, or the rounded corner reads as stair-steps.
    mask = mask.filter(ImageFilter.GaussianBlur(0.6))

    cut = art.copy()
    cut.putalpha(mask)
    print(f"made {len(outside):,} px transparent (background and outline ring)")
    return cut


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing source artwork: {SOURCE}")

    art = cut_out_tile(Image.open(SOURCE))
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
