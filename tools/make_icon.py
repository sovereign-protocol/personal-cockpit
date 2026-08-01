#!/usr/bin/env python3
"""Draw the application icons from the same geometry the in-app header uses.

The manifest's icon is four rounded squares on a 24-unit grid - the
"four quadrant button" DESIGN_UI_CONSISTENCY describes. This renders Windows
and macOS icon files for the frozen applications, so the window, taskbar and
file listing show the same mark the aggregator shows inside the application.

Development only. Pillow is not a dependency of this package; the generated
icon is committed, so nobody needs this to build.

    python -m pip install pillow
    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


# Not src/s_cockpit/assets/, which is packaged and served to the
# browser. This one is consumed by PyInstaller at build time and ships inside
# the executable rather than beside it.
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "packaging"
WINDOWS_OUTPUT = OUTPUT_DIR / "sovereign.ico"
MACOS_OUTPUT = OUTPUT_DIR / "sovereign.icns"

# Straight from s_cockpit.application.APPLICATION_MANIFEST.icon: four
# 7x7 squares with radius 1, at these origins on a 24-unit viewBox.
GRID = 24.0
SQUARE = 7.0
RADIUS = 1.0
ORIGINS = ((3, 3), (14, 3), (3, 14), (14, 14))

TILE = "#161b22"       # shell chrome, so the icon sits on the app's own surface
MARK = "#3fb99b"       # --teal lifted for legibility against the tile
WINDOWS_SIZES = (16, 24, 32, 48, 64, 128, 256)
MACOS_SIZES = (32, 64, 128, 256, 512, 1024)

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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    windows_frames = [render(size) for size in WINDOWS_SIZES]
    # Pillow writes every requested size into one .ico from the largest frame.
    windows_frames[-1].save(
        WINDOWS_OUTPUT,
        format="ICO",
        sizes=[(size, size) for size in WINDOWS_SIZES],
    )

    macos_frames = [render(size) for size in MACOS_SIZES]
    macos_frames[-1].save(
        MACOS_OUTPUT,
        format="ICNS",
        append_images=macos_frames[:-1],
    )

    for output in (WINDOWS_OUTPUT, MACOS_OUTPUT):
        print(f"wrote {output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
