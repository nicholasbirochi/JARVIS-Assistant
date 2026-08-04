"""One-off script: rasterizes two SF Symbols (Apple's own icon system --
the same one every other native menu-bar icon uses) into template PNGs for
JarvisMenuBarApp. Generated once and committed as static assets in
jarvis/assets/ -- no need to re-render at every app launch.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep, NSImage  # noqa: E402

ASSETS_DIR = Path(__file__).resolve().parent.parent / "jarvis" / "assets"

ICONS = {
    "icon_off.png": "speaker.slash.fill",
    "icon_on.png": "speaker.wave.2.fill",
}

RENDER_SIZE_PX = 128  # rumps resizes to 20x20 for display; render large for crispness


def render_sf_symbol_to_png(symbol_name: str, output_path: Path) -> None:
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, None)
    if image is None:
        raise RuntimeError(f"SF Symbol não encontrado: {symbol_name!r}")
    image.setTemplate_(True)
    image.setSize_((RENDER_SIZE_PX, RENDER_SIZE_PX))

    tiff_data = image.TIFFRepresentation()
    bitmap_rep = NSBitmapImageRep.imageRepWithData_(tiff_data)
    png_data = bitmap_rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    png_data.writeToFile_atomically_(str(output_path), True)


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, symbol_name in ICONS.items():
        output_path = ASSETS_DIR / filename
        render_sf_symbol_to_png(symbol_name, output_path)
        print(f"{symbol_name} -> {output_path}")


if __name__ == "__main__":
    main()
