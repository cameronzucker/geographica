"""
Capture README screenshots from the live Geographica stack.

Each function captures one shot. Functions are independent — invoke any
subset via --shots argument:

  python3 scripts/capture_readme_screenshots.py --shots 3d-terrain,voice-search

Pre-flight: live stack must be running (`docker compose ps` shows 7 services
Up (healthy)). Default base URL is http://localhost:8093.

Install dependencies (run once):
    pip install --user --break-system-packages -r scripts/requirements.txt
    python3 -m playwright install chromium

Deps live in ~/.local (user site-packages) so this script runs under
/usr/bin/python3 without coupling to setup/.venv. Chromium browser binary
is cached at ~/.cache/ms-playwright/ (user-account-scoped, not venv-scoped).
"""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
GALLERY_DIR = OUT_DIR / "gallery"
DEFAULT_URL = "http://localhost:8093"
ADMIN_URL   = "http://localhost:8097"

VIEWPORT = {"width": 1280, "height": 800}
PHONE_VIEWPORT = {"width": 390, "height": 844}  # iPhone 14 Pro proportions


async def shot_3d_terrain(page, url):
    """3D terrain w/ hillshade + exaggeration slider visible."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Open Layers panel
    await page.locator("button.tab-btn[data-panel='layers-panel']").click()
    # Toggle 3D terrain (slider auto-reveals when terrain toggle is on)
    await page.locator("text=3D Terrain").click()
    await page.wait_for_timeout(2000)  # let tiles render
    await page.screenshot(path=str(OUT_DIR / "3d-terrain.png"), full_page=False)


async def shot_voice_search(page, url):
    """Voice search active + result list ('gas stations along route') + map pins."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Type query directly (skip mic since Playwright can't easily mock audio input)
    await page.locator("#search-input").fill("gas stations along my route")
    await page.locator("#search-input").press("Enter")
    await page.wait_for_selector(".search-result", timeout=10000)
    await page.wait_for_timeout(1500)
    await page.screenshot(path=str(OUT_DIR / "voice-search.png"), full_page=False)


async def shot_public_lands(page, url):
    """Public lands layer with agency-colored fills + tribal stripes + legend."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    await page.locator("button.tab-btn[data-panel='layers-panel']").click()
    await page.locator("text=Public Lands").click()
    # (default view; T5.4 will tune framing if needed)
    await page.wait_for_timeout(2000)
    await page.screenshot(path=str(OUT_DIR / "public-lands.png"), full_page=False)


async def shot_admin_pipeline(page, url):
    """Admin → Pipelines tab — 7 source cards + minimap + active progress."""
    await page.goto(ADMIN_URL)
    await page.wait_for_load_state("networkidle")
    await page.locator("text=Pipelines").click()
    await page.wait_for_timeout(1500)
    await page.screenshot(path=str(OUT_DIR / "admin-pipeline.png"), full_page=False)


async def shot_setup_wizard(page, url):
    """Setup wizard step 3 — clean dark mode, progress dots, professional."""
    await page.goto("http://localhost:8099/step/3")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    await page.screenshot(path=str(GALLERY_DIR / "setup-wizard.png"), full_page=False)


async def shot_kmz_overlay(page, url):
    """Drag-drop KMZ overlay + layer panel + custom icons rendered."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Trigger file input directly
    await page.set_input_files("input[type='file'][accept*='kmz']", "docs/Ham Radio Deployment Sites.kmz")
    await page.wait_for_timeout(2500)  # let icons load
    await page.screenshot(path=str(GALLERY_DIR / "kmz-overlay.png"), full_page=False)


async def shot_imagery_before_after(page, url):
    """Side-by-side: basemap only vs NAIP overlay enabled. Two captures + composited."""
    # Capture "before" (basemap only)
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    before = await page.screenshot(full_page=False)

    # Toggle NAIP imagery
    await page.locator("button.tab-btn[data-panel='layers-panel']").click()
    await page.locator("text=NOAA NAIP").click()
    await page.wait_for_timeout(3000)  # let imagery tiles load
    after = await page.screenshot(full_page=False)

    # Composite side-by-side via Pillow
    from PIL import Image
    import io
    bimg = Image.open(io.BytesIO(before))
    aimg = Image.open(io.BytesIO(after))
    composite = Image.new("RGB", (bimg.width + aimg.width + 8, max(bimg.height, aimg.height)), "white")
    composite.paste(bimg, (0, 0))
    composite.paste(aimg, (bimg.width + 8, 0))
    composite.save(GALLERY_DIR / "imagery-before-after.png")


SHOTS = {
    "3d-terrain":            (shot_3d_terrain,            VIEWPORT),
    "voice-search":          (shot_voice_search,          VIEWPORT),
    "public-lands":          (shot_public_lands,          VIEWPORT),
    "admin-pipeline":        (shot_admin_pipeline,        VIEWPORT),
    "setup-wizard":          (shot_setup_wizard,          VIEWPORT),
    "kmz-overlay":           (shot_kmz_overlay,           VIEWPORT),
    "imagery-before-after":  (shot_imagery_before_after,  VIEWPORT),
}


async def run(shots_to_capture, url):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for name in shots_to_capture:
            if name not in SHOTS:
                print(f"  ⚠ unknown shot: {name}; valid: {','.join(SHOTS)}")
                continue
            shot_fn, viewport = SHOTS[name]
            ctx = await browser.new_context(viewport=viewport, device_scale_factor=2)
            page = await ctx.new_page()
            print(f"  → capturing {name} …")
            try:
                await shot_fn(page, url)
                print(f"     ✓ saved")
            except Exception as e:
                print(f"     ✗ FAILED: {e}")
            await ctx.close()
        await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", default=",".join(SHOTS),
                        help="Comma-separated shot names")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    asyncio.run(run(args.shots.split(","), args.url))


if __name__ == "__main__":
    main()
