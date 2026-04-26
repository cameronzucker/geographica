"""
Apply visual framing to README screenshots.

Desktop shots: subtle 1px border (#d0d7de) + soft drop shadow on a transparent
canvas. Mobile shots: composite into a phone frame (deferred to T5.9 — falls
back to desktop framing if no template is present).

Idempotency: the framing operation grows the canvas to a deterministic size
(src_w + 2*PADDING, src_h + 2*PADDING + SHADOW_OFFSET_Y). Before processing,
the script reads the source PNG's "geographica-framed" PNG text marker; if
present, the file is skipped. The marker is written into the PIL Image
metadata on the first framed save.

Usage:
  python3 scripts/postprocess_screenshots.py                        # all
  python3 scripts/postprocess_screenshots.py --shots 3d-terrain     # one
  python3 scripts/postprocess_screenshots.py --shots a,b,c          # subset
  python3 scripts/postprocess_screenshots.py --force                # re-frame
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, PngImagePlugin

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
GALLERY_DIR = OUT_DIR / "gallery"
PHONE_FRAME_PATH = OUT_DIR / "_phone_frame_template.png"

DESKTOP_SHOTS = ["3d-terrain", "voice-search", "public-lands", "admin-pipeline", "hero-everything"]
GALLERY_SHOTS = ["setup-wizard", "kmz-overlay", "imagery-before-after"]
MOBILE_SHOTS = ["mobile-nav"]

BORDER_COLOR = (208, 215, 222, 255)  # #d0d7de — GitHub muted border
SHADOW_OFFSET = (0, 8)
SHADOW_BLUR = 16
SHADOW_OPACITY = 64
PADDING = 24

FRAMED_MARKER_KEY = "geographica-framed"
FRAMED_MARKER_VAL = "1"


def _is_already_framed(img: Image.Image) -> bool:
    """Detect prior framing via PNG text metadata sentinel."""
    info = getattr(img, "info", {}) or {}
    return info.get(FRAMED_MARKER_KEY) == FRAMED_MARKER_VAL


def _build_pnginfo() -> PngImagePlugin.PngInfo:
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text(FRAMED_MARKER_KEY, FRAMED_MARKER_VAL)
    return pnginfo


def desktop_frame(input_path: Path, output_path: Path, force: bool = False) -> str:
    """1px border + soft drop shadow on a transparent canvas. Returns status."""
    src = Image.open(input_path)
    if not force and _is_already_framed(src):
        return "skipped (already framed)"
    src = src.convert("RGBA")
    sw, sh = src.size

    canvas_w = sw + PADDING * 2
    canvas_h = sh + PADDING * 2 + SHADOW_OFFSET[1]
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Draw shadow first (full-rectangle dark fill, then blurred)
    shadow = Image.new("RGBA", (sw, sh), (0, 0, 0, SHADOW_OPACITY))
    shadow_blurred = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    canvas.paste(
        shadow_blurred,
        (PADDING + SHADOW_OFFSET[0], PADDING + SHADOW_OFFSET[1]),
        shadow_blurred,
    )

    # Draw the source image on top
    canvas.paste(src, (PADDING, PADDING), src)

    # 1px border
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        [(PADDING, PADDING), (PADDING + sw - 1, PADDING + sh - 1)],
        outline=BORDER_COLOR,
        width=1,
    )

    canvas.save(output_path, optimize=True, pnginfo=_build_pnginfo())
    return "framed"


def phone_frame(input_path: Path, output_path: Path, force: bool = False,
                frame_template: Path = PHONE_FRAME_PATH) -> str:
    """Composite a phone screenshot into a phone-frame template."""
    if not frame_template.exists():
        # Fallback: portrait desktop frame.
        print(f"  ⚠ phone frame template missing at {frame_template}; "
              f"falling back to desktop frame")
        return desktop_frame(input_path, output_path, force=force)

    src = Image.open(input_path)
    if not force and _is_already_framed(src):
        return "skipped (already framed)"
    src = src.convert("RGBA")
    frame = Image.open(frame_template).convert("RGBA")

    cutout_w, cutout_h = frame.size
    src_resized = src.resize((cutout_w, cutout_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    canvas.paste(src_resized, (0, 0), src_resized)
    canvas.paste(frame, (0, 0), frame)
    canvas.save(output_path, optimize=True, pnginfo=_build_pnginfo())
    return "phone-framed"


def _all_targets():
    return (
        [(OUT_DIR / f"{s}.png", OUT_DIR / f"{s}.png", "desktop") for s in DESKTOP_SHOTS]
        + [(GALLERY_DIR / f"{s}.png", GALLERY_DIR / f"{s}.png", "desktop") for s in GALLERY_SHOTS]
        + [(OUT_DIR / f"{s}.png", OUT_DIR / f"{s}.png", "phone") for s in MOBILE_SHOTS]
    )


def _resolve_shot(name: str):
    """Map a bare shot name (e.g. 'kmz-overlay') back to its (in, out, kind) tuple."""
    for tup in _all_targets():
        inpath, _outpath, _kind = tup
        if inpath.stem == name:
            return tup
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shots",
        default="all",
        help="'all' (default) or a comma-separated list of shot stems "
             "(e.g. '3d-terrain,voice-search').",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-frame even if the framed-marker is already present.",
    )
    args = parser.parse_args()

    if args.shots == "all":
        targets = _all_targets()
    else:
        names = [s.strip() for s in args.shots.split(",") if s.strip()]
        targets = []
        for name in names:
            tup = _resolve_shot(name)
            if tup is None:
                print(f"  ⚠ unknown shot: {name} (skipping)")
                continue
            targets.append(tup)

    for inpath, outpath, kind in targets:
        if not inpath.exists():
            print(f"  ⚠ skipping (missing): {inpath.name}")
            continue
        if kind == "desktop":
            status = desktop_frame(inpath, outpath, force=args.force)
        elif kind == "phone":
            status = phone_frame(inpath, outpath, force=args.force)
        else:
            print(f"  ⚠ unknown kind '{kind}' for {inpath.name}")
            continue
        print(f"  ✓ {inpath.name} → {status}")


if __name__ == "__main__":
    main()
