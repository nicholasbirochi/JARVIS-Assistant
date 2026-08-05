"""One-off script: rasterizes two SF Symbols (Apple's own icon system --
the same one every other native menu-bar icon uses) into template PNGs for
JarvisMenuBarApp. Generated once and committed as static assets in
jarvis/assets/ -- no need to re-render at every app launch.

Renders by drawing the symbol's vector artwork directly into a bitmap
context at the target pixel size (via NSImageSymbolConfiguration + an
explicit NSGraphicsContext), instead of exporting NSImage's cached default
TIFFRepresentation. The naive approach (setSize_ + TIFFRepresentation)
just stretches whatever low-resolution bitmap AppKit had already cached
for on-screen use -- it looks blurry once scaled. Drawing at full pixel
size produces a crisp result at any display density (menu bar is 20pt,
but Retina needs the extra pixels).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from AppKit import (  # noqa: E402
    NSApplication,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSCompositingOperationSourceOver,
    NSDeviceRGBColorSpace,
    NSFontWeightRegular,
    NSGraphicsContext,
    NSImage,
    NSImageSymbolConfiguration,
    NSImageSymbolScaleLarge,
    NSMakeRect,
    NSZeroRect,
)

# A real NSApplication instance is required before any AppKit drawing call
# (NSGraphicsContext, NSBitmapImageRep) works correctly when run as a
# plain script rather than from inside an app's run loop.
NSApplication.sharedApplication()

ASSETS_DIR = Path(__file__).resolve().parent.parent / "jarvis" / "assets"

ICONS = {
    "icon_off.png": "speaker.slash.fill",
    "icon_on.png": "speaker.wave.2.fill",
}

# rumps displays at 20x20pt; render well above the 2x/3x Retina ceiling
# (60px) so the icon is always drawn down, never up.
RENDER_SIZE_PX = 256
SYMBOL_POINT_SIZE = 200  # inset from RENDER_SIZE_PX so the glyph isn't clipped


def render_sf_symbol_to_png(symbol_name: str, output_path: Path) -> None:
    base_image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, None)
    if base_image is None:
        raise RuntimeError(f"SF Symbol não encontrado: {symbol_name!r}")

    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
        SYMBOL_POINT_SIZE, NSFontWeightRegular, NSImageSymbolScaleLarge
    )
    symbol_image = base_image.imageWithSymbolConfiguration_(config)
    if symbol_image is None:
        raise RuntimeError(f"Falha ao aplicar configuração ao símbolo: {symbol_name!r}")
    symbol_image.setTemplate_(True)

    bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, RENDER_SIZE_PX, RENDER_SIZE_PX, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    bitmap.setSize_((RENDER_SIZE_PX, RENDER_SIZE_PX))

    # SF Symbols aren't square -- speaker.wave.2.fill is noticeably wider
    # than tall (the wave arcs extend sideways), while speaker.slash.fill
    # is closer to square. Drawing straight into the full square canvas
    # stretches non-square symbols to fill it, distorting the glyph.
    # Aspect-fit into the canvas instead, centered, so nothing gets
    # squashed in either direction.
    symbol_size = symbol_image.size()
    scale = min(RENDER_SIZE_PX / symbol_size.width, RENDER_SIZE_PX / symbol_size.height)
    draw_width = symbol_size.width * scale
    draw_height = symbol_size.height * scale
    dest_rect = NSMakeRect(
        (RENDER_SIZE_PX - draw_width) / 2,
        (RENDER_SIZE_PX - draw_height) / 2,
        draw_width,
        draw_height,
    )

    NSGraphicsContext.saveGraphicsState()
    try:
        context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
        NSGraphicsContext.setCurrentContext_(context)
        symbol_image.drawInRect_fromRect_operation_fraction_(
            dest_rect,
            NSZeroRect,
            NSCompositingOperationSourceOver,
            1.0,
        )
    finally:
        NSGraphicsContext.restoreGraphicsState()

    png_data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    png_data.writeToFile_atomically_(str(output_path), True)


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, symbol_name in ICONS.items():
        output_path = ASSETS_DIR / filename
        render_sf_symbol_to_png(symbol_name, output_path)
        print(f"{symbol_name} -> {output_path}")


if __name__ == "__main__":
    main()
