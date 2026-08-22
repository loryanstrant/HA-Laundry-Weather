#!/usr/bin/env python3
"""Render the brand icon PNGs that HACS looks for.

HACS checks for `custom_components/<domain>/brand/icon.png` (256px) and
`icon@2x.png` (512px), falling back to the Home Assistant brands repository if
they are absent — and failing validation if neither exists.

The shapes live in `brand/icon.svg` so they stay editable; this renders them.
Run it in a container with a browser, which the Rufus container has not got:

    ssh blaster "sudo -n docker run --rm --network none -v <repo>:/repo -w /repo \\
        -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \\
        mcr.microsoft.com/playwright/python:v1.49.0-noble \\
        bash -lc 'pip install -q playwright==1.49.0 && python scripts/make_brand_icons.py'"

The outputs are committed, so nobody needs to re-run this to build the repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BRAND = Path(__file__).resolve().parent.parent / "custom_components" / "laundry_weather" / "brand"
SOURCE = BRAND / "icon.svg"
SIZES = {"icon.png": 256, "icon@2x.png": 512}


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing {SOURCE}")

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb"])
        for name, size in SIZES.items():
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(
                "<style>html,body{margin:0;padding:0}svg{display:block}</style>"
                + SOURCE.read_text(encoding="utf-8").replace(
                    'width="256" height="256"',
                    f'width="{size}" height="{size}"',
                )
            )
            page.wait_for_timeout(200)
            page.screenshot(path=str(BRAND / name), omit_background=True)
            page.close()
            print(f"{name:<12} {size}x{size}  {(BRAND / name).stat().st_size // 1024} KB")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
