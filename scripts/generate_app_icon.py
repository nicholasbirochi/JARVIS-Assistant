"""One-off script: renders JARVIS.app's icon -- a dark rounded-square
background with a glowing blue orb, matching the visualizer HUD's own
look (jarvis/visualizer/page.html's core sphere) -- at every size macOS's
.icns format needs, then packs them into an .iconset and converts via
`iconutil` (built into macOS, no dependency). Generated once and
committed as a static asset in jarvis/assets/ -- no need to re-render at
build time.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
ICNS_OUTPUT = Path(__file__).resolve().parent.parent / "jarvis" / "assets" / "AppIcon.icns"

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
        bg_path.addClip()  # keep the glow/orb from spilling past the rounded corners

        center = NSMakePoint(size / 2, size / 2)

        # Soft ambient glow behind the orb.
        glow = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
            [
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.18, 0.71, 0.91, 0.55),
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.18, 0.71, 0.91, 0.0),
            ],
            [0.0, 1.0],
            rgb,
        )
        glow.drawFromCenter_radius_toCenter_radius_options_(center, 0, center, size * 0.46, 0)

        # The orb itself -- bright white-blue center fading to the state
        # blue at the rim, same palette as the HUD's core sphere, with an
        # off-center highlight for a bit of dimensionality.
        orb_radius = size * 0.30
        orb_center = NSMakePoint(size / 2 - orb_radius * 0.18, size / 2 + orb_radius * 0.18)
        orb_gradient = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
            [
                NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 1.0, 1.0, 1.0),
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.5, 0.89, 1.0, 1.0),
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.12, 0.45, 0.66, 1.0),
            ],
            [0.0, 0.45, 1.0],
            rgb,
        )
        orb_gradient.drawFromCenter_radius_toCenter_radius_options_(orb_center, 0, center, orb_radius, 0)
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
