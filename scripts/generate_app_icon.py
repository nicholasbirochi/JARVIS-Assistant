"""One-off script: renders JARVIS.app's icon -- a dark rounded-square
background with the visualizer HUD's own particle-sphere look
(jarvis/visualizer/page.html's constellation of connected dots), frozen
at one fixed, pleasing rotation since an icon can't animate -- at every
size macOS's .icns format needs, then packs them into an .iconset and
converts via `iconutil` (built into macOS, no dependency). Generated once
and committed as a static asset in jarvis/assets/ -- no need to
re-render at build time.
"""

from __future__ import annotations

import math
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AppKit import (  # noqa: E402
    NSApplication,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSColorSpace,
    NSDeviceRGBColorSpace,
    NSGradient,
    NSGraphicsContext,
    NSMakePoint,
    NSMakeRect,
)

NSApplication.sharedApplication()

ICONSET_DIR = Path(__file__).resolve().parent.parent / "build" / "JARVIS.iconset"
ICNS_OUTPUT = Path(__file__).resolve().parent.parent / "src" / "jarvis" / "assets" / "AppIcon.icns"

# (filename, pixel size) -- exactly what `iconutil -c icns` expects to find
# inside an .iconset directory.
SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

# Same sphere-distribution idea as the HUD's canvas (theta/phi uniform over
# a sphere surface), but far fewer points and a single frozen rotation --
# a still image with 260 dots would just read as noise, especially at
# 16-32px sizes where most of these are actually seen day to day (Dock,
# Finder list view, menu bar "About" panel).
_rng = random.Random(7)  # fixed seed -- same icon every time this script runs
PARTICLES = [
    (_rng.uniform(0, 2 * math.pi), math.acos(2 * _rng.uniform(0, 1) - 1)) for _ in range(70)
]
ROTATION = 0.5  # radians -- picked by eye for a balanced-looking frozen pose


def _project(size: int) -> list[tuple[float, float, float]]:
    R = size * 0.30
    cx = cy = size / 2
    points = []
    for theta, phi in PARTICLES:
        t = theta + ROTATION
        x3 = math.sin(phi) * math.cos(t)
        y3 = math.cos(phi)
        z3 = math.sin(phi) * math.sin(t)
        points.append((cx + x3 * R, cy + y3 * R * 0.94, z3))
    points.sort(key=lambda p: p[2])  # back-to-front
    return points


def draw_icon(size: int, output_path: Path) -> None:
    bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    bitmap.setSize_((size, size))

    NSGraphicsContext.saveGraphicsState()
    try:
        context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
        NSGraphicsContext.setCurrentContext_(context)

        rgb = NSColorSpace.genericRGBColorSpace()

        # Rounded-square background, matching the HUD's near-black navy (#030711).
        corner_radius = size * 0.22
        bg_rect = NSMakeRect(0, 0, size, size)
        bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bg_rect, corner_radius, corner_radius)
        NSColor.colorWithSRGBRed_green_blue_alpha_(0.012, 0.027, 0.067, 1.0).setFill()
        bg_path.fill()
        bg_path.addClip()  # keep the glow/dots from spilling past the rounded corners

        center = NSMakePoint(size / 2, size / 2)

        # Soft ambient glow behind the sphere.
        glow = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
            [
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.18, 0.71, 0.91, 0.5),
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.18, 0.71, 0.91, 0.0),
            ],
            [0.0, 1.0],
            rgb,
        )
        glow.drawFromCenter_radius_toCenter_radius_options_(center, 0, center, size * 0.46, 0)

        points = _project(size)
        max_dist = size * 0.16

        # Constellation lines between nearby front-facing dots, drawn
        # before the dots themselves so dots sit on top.
        for i in range(len(points)):
            ax, ay, az = points[i]
            if az < 0:
                continue
            for j in range(i + 1, len(points)):
                bx, by, bz = points[j]
                if bz < 0:
                    continue
                dist = math.hypot(ax - bx, ay - by)
                if dist >= max_dist:
                    continue
                depth = ((az + bz) / 2 + 1) / 2
                alpha = (1 - dist / max_dist) * (0.15 + 0.35 * depth)
                line = NSBezierPath.bezierPath()
                line.moveToPoint_((ax, ay))
                line.lineToPoint_((bx, by))
                line.setLineWidth_(max(0.6, size * 0.0025))
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.35, 0.82, 1.0, alpha).setStroke()
                line.stroke()

        # The dots themselves -- brighter/bigger toward the front (higher z).
        for x, y, z in points:
            depth = (z + 1) / 2
            dot_r = size * (0.010 + 0.018 * depth)
            NSColor.colorWithSRGBRed_green_blue_alpha_(
                0.55 + 0.45 * depth, 0.85 + 0.15 * depth, 1.0, 0.55 + 0.45 * depth
            ).setFill()
            NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - dot_r, y - dot_r, dot_r * 2, dot_r * 2)).fill()
    finally:
        NSGraphicsContext.restoreGraphicsState()

    png_data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    png_data.writeToFile_atomically_(str(output_path), True)


def main() -> None:
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    for filename, size in SIZES:
        draw_icon(size, ICONSET_DIR / filename)
        print(f"{filename} ({size}px)")

    ICNS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_OUTPUT)], check=True)
    print(f"-> {ICNS_OUTPUT}")


if __name__ == "__main__":
    main()
