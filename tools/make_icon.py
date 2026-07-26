#!/usr/bin/env python3
"""Draw the application icon from the same geometry the in-app header uses.

The manifest's icon is four rounded squares on a 24-unit grid - the
"four quadrant button" DESIGN_UI_CONSISTENCY describes. This renders that to
a multi-size .ico for the frozen executable, so the window, taskbar and file
listing show the same mark the aggregator shows inside the application.

Development only. Pillow is not a dependency of this package; the generated
icon is committed, so nobody needs this to build.

    python -m pip install pillow
    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


# Not src/personal_cockpit/assets/, which is packaged and served to the
# browser. This one is consumed by PyInstaller at build time and ships inside
# the executable rather than beside it.
OUTPUT = Path(__file__).resolve().parents[1] / "packaging" / "sovereign.ico"

# Straight from personal_cockpit.application.APPLICATION_MANIFEST.icon: four
# 7x7 squares with radius 1, at these origins on a 24-unit viewBox.
GRID = 24.0
SQUARE = 7.0
RADIUS = 1.0
ORIGINS = ((3, 3), (14, 3), (3, 14), (14, 14))

TILE = "#161b22"       # shell chrome, so the icon sits on the app's own surface
MARK = "#3fb99b"       # --teal lifted for legibility against the tile
SIZES = (16, 24, 32, 48, 64, 128, 256)

# Draw large and downsample: rounded corners at 16px are jagged otherwise.
SUPERSAMPLE = 8


def render(size: int) -> Image.Image:
    canvas = size * SUPERSAMPLE
    scale = canvas / GRID
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # A rounded tile rather than bare marks: at 16px four separate shapes read
    # as noise, and every other desktop icon is a solid silhouette.
    draw.rounded_rectangle(
        (0, 0, canvas - 1, canvas - 1),
        radius=canvas * 0.18,
        fill=TILE,
    )
    for x, y in ORIGINS:
        draw.rounded_rectangle(
            (x * scale, y * scale, (x + SQUARE) * scale, (y + SQUARE) * scale),
            radius=RADIUS * scale * 1.6,
            fill=MARK,
        )
    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [render(size) for size in SIZES]
    # Pillow writes every requested size into one .ico from the largest frame.
    frames[-1].save(OUTPUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes, {len(SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
