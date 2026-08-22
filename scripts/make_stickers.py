#!/usr/bin/env python3
"""Turn the source sticker photographs into the four bundled card banners.

The supplied artwork carries its speech bubble text baked into the picture, so
the Klingon toggle cannot simply swap a string. Rather than overlay text onto
the image at runtime — which would mean the card carrying per-image
coordinates that go stale the moment somebody uses a different picture — the
Klingon wording is baked in here, once, and committed. The card then only ever
picks one of four static files and holds no coordinates at all.

Outputs, into `custom_components/laundry_weather/www/`:

    worf-good.png           worf-bad.png
    worf-good-klingon.png   worf-bad-klingon.png

Run it inside a container that has fonts — the Rufus container has none:

    ssh blaster "sudo -n docker run --rm -v <repo>:/repo -w /repo \\
        mcr.microsoft.com/playwright/python:v1.49.0-noble \\
        bash -lc 'pip install -q pillow && python scripts/make_stickers.py'"

The outputs are committed, so nobody needs to re-run this to build the repo.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
WWW = REPO / "custom_components" / "laundry_weather" / "www"

#: Shipping width. The sources are ~1 MB each at 1021px; a card banner is never
#: rendered wider than this, and quantising a flat cartoon to 128 colours costs
#: nothing visible while taking each file to around 55 KB.
TARGET_WIDTH = 600
PALETTE_COLOURS = 128


@dataclass(frozen=True)
class Sticker:
    source: str
    stem: str
    klingon: str
    alt: str
    #: Identifies the speech bubble fill. Restricted to the right-hand side of
    #: the picture because the red test also matches the uniform stripe across
    #: Worf's chest — found the hard way while measuring.
    is_bubble: callable
    search_from: float = 0.0
    #: Baked lettering inside the bubble: dark on the yellow, light on the red.
    is_lettering: callable = None


def yellow(r: int, g: int, b: int) -> bool:
    return r > 200 and g > 170 and b < 110


def red(r: int, g: int, b: int) -> bool:
    return r > 150 and g < 70 and b < 70


STICKERS = (
    Sticker(
        source="worf-dry.png",
        stem="worf-good",
        klingon="QaDmoHlu'meH\nQaQ jajvam",
        alt="It is a good day to dry",
        is_bubble=yellow,
        search_from=0.45,
        is_lettering=lambda r, g, b: r < 120 and g < 120 and b < 120,
    ),
    Sticker(
        source="worf-not-dry.png",
        stem="worf-bad",
        klingon="QaDmoHlu'meH\nQaQbe' jajvam",
        alt="It is not a good day to dry",
        is_bubble=red,
        search_from=0.50,
        is_lettering=lambda r, g, b: r > 190 and g > 190 and b > 190,
    ),
)


def load_trimmed(path: Path) -> Image.Image:
    """Open a source sticker and crop away its transparent margin."""
    image = Image.open(path).convert("RGBA")
    box = image.getchannel("A").getbbox()
    if box is None:
        raise SystemExit(f"{path.name} is entirely transparent")
    return image.crop(box)


def bubble_box(image: Image.Image, sticker: Sticker) -> tuple[int, int, int, int]:
    """Find the speech bubble by its fill colour."""
    width, height = image.size
    pixels = image.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(0, height, 2):
        for x in range(int(width * sticker.search_from), width, 2):
            r, g, b, a = pixels[x, y]
            if a > 200 and sticker.is_bubble(r, g, b):
                xs.append(x)
                ys.append(y)
    if not xs:
        raise SystemExit(f"{sticker.source}: could not find the speech bubble")
    return min(xs), min(ys), max(xs), max(ys)


def bubble_fill(image: Image.Image, box: tuple[int, int, int, int],
                sticker: Sticker) -> tuple[int, int, int, int]:
    """The most common bubble colour, so the patch is an exact match."""
    x0, y0, x1, y1 = box
    counts: dict[tuple[int, int, int, int], int] = {}
    pixels = image.load()
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            value = pixels[x, y]
            if value[3] > 200 and sticker.is_bubble(*value[:3]):
                counts[value] = counts.get(value, 0) + 1
    return max(counts, key=counts.get)


def _largest_blob(points: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """Return the biggest 4-connected component of a point set."""
    unvisited = set(points)
    best: set[tuple[int, int]] = set()
    while unvisited:
        seed = unvisited.pop()
        blob = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for neighbour in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if neighbour in unvisited:
                    unvisited.discard(neighbour)
                    blob.add(neighbour)
                    stack.append(neighbour)
        if len(blob) > len(best):
            best = blob
    return best


def erase_lettering(
    image: Image.Image,
    box: tuple[int, int, int, int],
    sticker: Sticker,
    fill: tuple[int, int, int, int],
) -> tuple[int, tuple[int, int, int, int]]:
    """Repaint the whole bubble interior, erasing the baked English wording.

    Two things had to be got right here, both learned by getting them wrong:

    A bounding *rectangle* around the bubble also covers part of Worf's
    shoulder, so erasing "dark pixels in the rectangle" turned his uniform the
    colour of the speech bubble. The region is therefore found by flooding
    outward from the middle of the bubble across pixels that are either bubble
    fill or lettering — the star's black outline stops the flood, giving its
    true shape rather than its bounding box.

    Erasing only pixels that *match* the lettering test left the anti-aliased
    edges behind, so the English ghosted through underneath the Klingon. Every
    pixel in the flooded region is repainted instead, which removes the
    lettering completely because the flood already includes it.

    Returns the pixel count and the flooded region's own bounding box. That box
    is what the Klingon is placed against, because the colour-detected one is
    polluted by the gold pips on Worf's collar and his combadge, which are near
    enough to the yellow bubble to pass the test.
    """
    x0, y0, x1, y1 = box
    pixels = image.load()

    # The lettering is the same black as the star's own outline, so no colour
    # test can separate them. Geometry can: the letters sit entirely enclosed
    # by bubble fill, while the outline lies outside it. So grow the fill
    # region, then fill whatever holes it encloses — those holes are the
    # letters, and the outline survives because it was never enclosed.
    region: set[tuple[int, int]] = set()
    stack: list[tuple[int, int]] = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            r, g, b, a = pixels[x, y]
            if a > 200 and sticker.is_bubble(r, g, b):
                region.add((x, y))
                stack.append((x, y))
    if not stack:
        raise SystemExit(f"{sticker.source}: found no bubble fill to seed from")

    # Grow one step across the anti-aliased rim where a letter meets the fill.
    # Those pixels are neither colour, and leaving them behind shows up as a
    # halo of the old wording under the new.
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in region or not (x0 <= nx <= x1 and y0 <= ny <= y1):
                continue
            r, g, b, a = pixels[nx, ny]
            if a > 200 and (
                sticker.is_bubble(r, g, b) or sticker.is_lettering(r, g, b)
            ):
                region.add((nx, ny))
                stack.append((nx, ny))

    # Keep only the largest blob. The colour tests also match the gold pips on
    # Worf's collar and his combadge, which are close enough to the yellow
    # bubble to pass; left in, they stretched the bounding box downwards and
    # the Klingon ended up sitting low and off to one side of the star.
    region = _largest_blob(region)

    xs = [p[0] for p in region]
    ys = [p[1] for p in region]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)

    # Anything in the bubble's box that cannot be reached from its edge without
    # crossing the fill is enclosed by the fill, and is therefore lettering.
    outside: set[tuple[int, int]] = set()
    for x in range(bx0, bx1 + 1):
        stack += [(x, by0), (x, by1)]
    for y in range(by0, by1 + 1):
        stack += [(bx0, y), (bx1, y)]
    stack = [p for p in stack if p not in region]
    outside.update(stack)
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (bx0 <= nx <= bx1 and by0 <= ny <= by1):
                continue
            if (nx, ny) in outside or (nx, ny) in region:
                continue
            outside.add((nx, ny))
            stack.append((nx, ny))

    repainted = 0
    for y in range(by0, by1 + 1):
        for x in range(bx0, bx1 + 1):
            if (x, y) not in outside:
                pixels[x, y] = fill
                repainted += 1

    return repainted, (bx0, by0, bx1, by1)


#: Optional pIqaD (Klingon script) face, used only when `--piqad` is passed.
#: Not committed: it is licensed for personal use, which does not cover
#: redistributing it to everyone who installs this. Only the rendered pixels
#: ship, which is what this whole script already does.
PIQAD_FONT = Path("/tmp/klingonfont/klingon.ttf")


def pick_font(size: int, piqad: bool = False) -> ImageFont.FreeTypeFont:
    """A bold italic face, falling back through what containers usually ship."""
    if piqad:
        if not PIQAD_FONT.exists():
            raise SystemExit(f"--piqad given but no font at {PIQAD_FONT}")
        return ImageFont.truetype(str(PIQAD_FONT), size)
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(
        "No usable font found. Run this inside a container that ships fonts —"
        " see the module docstring."
    )


def draw_klingon(image: Image.Image, box: tuple[int, int, int, int],
                 text: str, ink: tuple[int, int, int, int],
                 piqad: bool = False) -> None:
    """Centre the Klingon in the bubble, scaled to fit its flat middle."""
    x0, y0, x1, y1 = box
    # The star's points eat into the edges, so only the middle is safe to
    # write across.
    inset_x = (x1 - x0) * 0.17
    inset_y = (y1 - y0) * 0.20
    left, top = x0 + inset_x, y0 + inset_y
    right, bottom = x1 - inset_x, y1 - inset_y
    max_width, max_height = right - left, bottom - top

    draw = ImageDraw.Draw(image)
    size = int(max_height / 2)
    while size > 6:
        font = pick_font(size, piqad)
        bounds = draw.multiline_textbbox(
            (0, 0), text, font=font, spacing=size * 0.18, align="center"
        )
        if (bounds[2] - bounds[0]) <= max_width and (
            bounds[3] - bounds[1]
        ) <= max_height:
            break
        size -= 1
    else:
        raise SystemExit("Klingon text will not fit in the bubble")

    bounds = draw.multiline_textbbox(
        (0, 0), text, font=font, spacing=size * 0.18, align="center"
    )
    x = left + (max_width - (bounds[2] - bounds[0])) / 2 - bounds[0]
    y = top + (max_height - (bounds[3] - bounds[1])) / 2 - bounds[1]
    draw.multiline_text(
        (x, y), text, font=font, fill=ink, spacing=size * 0.18, align="center"
    )


def save(image: Image.Image, path: Path) -> int:
    """Downscale, quantise and write. Returns the file size in bytes."""
    height = round(image.height * TARGET_WIDTH / image.width)
    resized = image.resize((TARGET_WIDTH, height), Image.LANCZOS)
    # Quantising keeps the alpha channel and takes a flat cartoon from ~360 KB
    # to ~55 KB with no visible loss.
    quantised = resized.quantize(colors=PALETTE_COLOURS, method=Image.FASTOCTREE)
    quantised.save(path, "PNG", optimize=True)
    return path.stat().st_size


PIQAD = "--piqad" in sys.argv


def main() -> int:
    WWW.mkdir(parents=True, exist_ok=True)
    for sticker in STICKERS:
        source = REPO / sticker.source
        if not source.exists():
            raise SystemExit(f"missing source artwork: {source}")

        plain = load_trimmed(source)
        box = bubble_box(plain, sticker)
        fill = bubble_fill(plain, box, sticker)

        size = save(plain, WWW / f"{sticker.stem}.png")
        print(f"{sticker.stem}.png            {size // 1024:>3} KB   bubble={box} fill={fill}")

        klingon = plain.copy()
        erased, bubble = erase_lettering(klingon, box, sticker, fill)
        # Dark ink on the yellow bubble, light on the red — matching whatever
        # the original lettering did.
        ink = (26, 20, 12, 255) if sum(fill[:3]) > 380 else (255, 255, 255, 255)
        draw_klingon(klingon, bubble, sticker.klingon, ink, piqad=PIQAD)

        size = save(klingon, WWW / f"{sticker.stem}-klingon.png")
        print(
            f"{sticker.stem}-klingon.png    {size // 1024:>3} KB   "
            f"repainted {erased:,} px, bubble={bubble}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
