#!/usr/bin/env python3
"""Generate favicon assets from docs/geographica_favicon.png.

Produces three derivatives in each of three HTML entry point directories:

- favicon.ico         multi-size bundle (16, 32, 48) for legacy browsers
- favicon-32.png      32x32 PNG for modern browsers (preferred over .ico)
- apple-touch-icon.png 180x180 PNG for iOS home-screen bookmarks, composited
                      onto opaque white so iOS doesn't render its default
                      background through transparent pixels

Target directories:
- frontend/
- frontend/config/
- setup/static/

Re-run this script any time docs/geographica_favicon.png changes.
Requires Pillow (already in scripts/requirements.txt for the data pipeline).
"""
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "docs" / "geographica_favicon.png"

TARGETS = [
    REPO_ROOT / "frontend",
    REPO_ROOT / "frontend" / "config",
    REPO_ROOT / "setup" / "static",
]

ICO_SIZES = [(16, 16), (32, 32), (48, 48)]
PNG_SIZE = (32, 32)
APPLE_SIZE = (180, 180)
APPLE_BG = (255, 255, 255)


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"source image not found: {SOURCE}")

    src = Image.open(SOURCE).convert("RGBA")
    print(f"source: {SOURCE.relative_to(REPO_ROOT)} ({src.size[0]}x{src.size[1]})")

    ico_master = src.resize((256, 256), Image.LANCZOS)
    png32 = src.resize(PNG_SIZE, Image.LANCZOS)

    apple_bg = Image.new("RGB", src.size, APPLE_BG)
    apple_bg.paste(src, mask=src.split()[3])
    apple_sized = apple_bg.resize(APPLE_SIZE, Image.LANCZOS)

    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        rel = target.relative_to(REPO_ROOT)

        ico_path = target / "favicon.ico"
        ico_master.save(ico_path, format="ICO", sizes=ICO_SIZES)

        png_path = target / "favicon-32.png"
        png32.save(png_path, format="PNG", optimize=True)

        apple_path = target / "apple-touch-icon.png"
        apple_sized.save(apple_path, format="PNG", optimize=True)

        print(f"  wrote {rel}/{{favicon.ico, favicon-32.png, apple-touch-icon.png}}")


if __name__ == "__main__":
    main()
