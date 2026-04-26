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
# Admin/config UI is served at /config/ on a sibling port (the main frontend's
# Admin tab links out to it). There is no separate admin-only top-level URL.
CONFIG_URL  = "http://localhost:8097/config/"
WIZARD_URL  = "http://localhost:8099/"

VIEWPORT = {"width": 1280, "height": 800}
PHONE_VIEWPORT = {"width": 390, "height": 844}  # iPhone 14 Pro proportions

# Phoenix-area scene used for shots that need terrain/imagery/public-lands
# detail (default app center is [-111.9, 34.0] @ z6 — too zoomed-out for
# tiles to convey what the layer looks like).
SCENE_PHX = {"center": [-112.10, 33.55], "zoom": 12}
SCENE_GRAND_CANYON = {"center": [-112.14, 36.06], "zoom": 12, "pitch": 60, "bearing": -20}


async def _open_sidebar(page):
    """Click the hamburger button to open the sidebar (it's translateX(-100%) by default)."""
    try:
        await page.locator("#sidebar-toggle").click(timeout=3000)
        # transition is 0.3s
        await page.wait_for_timeout(400)
    except Exception:
        # Already open, or toggle not present — fall back to direct class add.
        await page.evaluate(
            """() => {
                const s = document.getElementById('sidebar');
                if (s && !s.classList.contains('open')) s.classList.add('open');
            }"""
        )
        await page.wait_for_timeout(200)


async def _fly_to(page, scene):
    """Jump the map to a scene and wait for tiles to settle.

    Uses window._geographicaMap (exposed by app.js) as the map handle.
    Falls back gracefully if the handle isn't ready yet.
    """
    await page.evaluate(
        """(scene) => new Promise((resolve) => {
            const m = window._geographicaMap;
            if (!m) { resolve(); return; }
            m.jumpTo({
                center: scene.center,
                zoom: scene.zoom,
                pitch: scene.pitch || 0,
                bearing: scene.bearing || 0,
            });
            // Resolve on idle (tiles loaded + animations done) or a 6s ceiling
            // so a missing imagery source can't hang the script.
            const t = setTimeout(resolve, 6000);
            m.once('idle', () => { clearTimeout(t); resolve(); });
        })""",
        scene,
    )


async def shot_3d_terrain(page, url):
    """3D terrain w/ hillshade + exaggeration slider visible."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Frame the Grand Canyon at a tilted angle so the 3D effect is dramatic.
    await _fly_to(page, SCENE_GRAND_CANYON)
    # Open the sidebar (hidden by default at this viewport) and Layers panel.
    await _open_sidebar(page)
    await page.locator("button.tab-btn[data-panel='layers-panel']").click()
    # Enable hillshade first (richer terrain shading visible behind 3D mesh)
    await page.locator("#toggle-hillshade").check()
    # Enable 3D terrain (slider auto-reveals when terrain toggle is on)
    await page.locator("#toggle-terrain").check()
    await page.wait_for_timeout(3500)  # let DEM tiles render at the new tilt
    await page.screenshot(
        path=str(OUT_DIR / "3d-terrain.png"),
        full_page=False,
        animations="disabled",
        timeout=60000,
    )


async def shot_voice_search(page, url):
    """Voice search active + result list ('gas stations along route') + map pins."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Frame Phoenix area so the result fitBounds has a sensible starting camera.
    await _fly_to(page, SCENE_PHX)
    # Type query directly (skip mic since Playwright can't easily mock audio input)
    await page.locator("#search-input").fill("gas stations along my route")
    await page.locator("#search-input").press("Enter")
    # Result list renders <li> children inside #search-results — wait for at
    # least one non-subtitle item.
    await page.wait_for_selector("#search-results li:not(.search-intent-subtitle)", timeout=15000)
    # Let fitBounds animate to the result extent + tiles to render at new zoom.
    await page.wait_for_timeout(3000)
    await page.screenshot(
        path=str(OUT_DIR / "voice-search.png"),
        full_page=False,
        animations="disabled",
        timeout=60000,
    )


async def shot_public_lands(page, url):
    """Public lands layer with agency-colored fills + tribal stripes + legend."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Northern Arizona — heavy Tribal + Forest + BLM + Park overlap; great
    # mosaic for showing agency colors and tribal stripes side-by-side.
    await _fly_to(page, {"center": [-110.5, 35.7], "zoom": 8})
    await _open_sidebar(page)
    await page.locator("button.tab-btn[data-panel='layers-panel']").click()
    await page.locator("#toggle-public-lands").check()
    await page.wait_for_timeout(2500)
    await page.screenshot(
        path=str(OUT_DIR / "public-lands.png"),
        full_page=False,
        animations="disabled",
        timeout=60000,
    )


async def shot_admin_pipeline(page, url):
    """Config panel → Pipelines tab — 7 source cards + minimap.

    The 'Admin' tab in the main frontend (port 8093) is a small status panel
    that links to the Config UI on port 8097/config/. The pipeline cards live
    on the Config UI, not in the main app.
    """
    await page.goto(CONFIG_URL)
    await page.wait_for_load_state("networkidle")
    # Click the Pipelines tab (data-tab='pipelines'), distinct from the main
    # frontend's data-panel sidebar tabs.
    await page.locator("button.tab-btn[data-tab='pipelines']").click()
    # Wait for pipeline cards (.source-card) to render; they're populated
    # by JS after fetching the source manifest.
    try:
        await page.wait_for_selector(".source-card", timeout=8000)
    except Exception:
        # Cards may not render if no sources are configured yet — capture anyway.
        pass
    await page.wait_for_timeout(2000)
    # full_page=True so all 7 source cards are captured below the fold;
    # the config panel is a long single-page layout, not a fixed viewport.
    await page.screenshot(
        path=str(OUT_DIR / "admin-pipeline.png"),
        full_page=True,
        animations="disabled",
        timeout=60000,
    )


async def shot_setup_wizard(page, url):
    """Setup wizard step 3 (Credentials) — dark mode, progress dots.

    The wizard runs as an on-demand FastAPI app on localhost:8099 and is
    launched separately via setup.sh; this function expects it to be
    already up and reachable.

    Note: dark mode is opt-in via prefers-color-scheme; the browser context
    is created with colorScheme='dark' in run() for this shot.

    Step navigation is internal — wizard-tab elements are display-only;
    showStep(n) is the JS API used by the SPA. We call it directly.
    """
    await page.goto(WIZARD_URL)
    await page.wait_for_load_state("networkidle")
    # Advance to step 3 (Credentials) via the SPA's own state-change function.
    await page.evaluate(
        """() => {
            if (typeof showStep === 'function') showStep(3);
        }"""
    )
    await page.wait_for_timeout(800)
    await page.screenshot(
        path=str(GALLERY_DIR / "setup-wizard.png"),
        full_page=False,
        animations="disabled",
        timeout=60000,
    )


async def shot_kmz_overlay(page, url):
    """KMZ overlay + layer panel + custom icons rendered."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Open Import panel so the drop-zone / file-input is in DOM context;
    # set_input_files works regardless of CSS visibility but we want the
    # panel's UI to be visible in the screenshot.
    await _open_sidebar(page)
    await page.locator("button.tab-btn[data-panel='import-panel']").click()
    # Use the explicit file input by id (more robust than attr-substring match).
    kmz_path = str(Path(__file__).resolve().parent.parent / "docs" / "Ham Radio Deployment Sites.kmz")
    await page.set_input_files("#file-input", kmz_path)
    # The KMZ contains Ham Radio sites (Arizona-area) — give it time to
    # parse + render icons + auto-fit bounds.
    await page.wait_for_timeout(3500)
    await page.screenshot(
        path=str(GALLERY_DIR / "kmz-overlay.png"),
        full_page=False,
        animations="disabled",
        timeout=60000,
    )


async def shot_imagery_before_after(page, url):
    """Side-by-side: basemap only vs basemap + NAIP NOAA. Two captures composited."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Frame downtown Phoenix at z14 — well within NOAA NAIP coverage and
    # close enough that the imagery upgrade is unmistakable.
    await _fly_to(page, {"center": [-112.074, 33.448], "zoom": 14})
    # Capture "before" (basemap only).
    await page.wait_for_timeout(1500)
    before = await page.screenshot(
        full_page=False, animations="disabled", timeout=60000
    )

    # Toggle NOAA NAIP imagery via its dynamic toggle — find by label text
    # ("NOAA NAIP") and click the sibling checkbox.
    await _open_sidebar(page)
    await page.locator("button.tab-btn[data-panel='layers-panel']").click()
    # The dynamic toggle is a div containing a checkbox + label spans. Click
    # the checkbox directly using a chained locator.
    noaa_row = page.locator("#imagery-toggles div", has_text="NOAA NAIP").first
    await noaa_row.locator("input[type='checkbox']").check()
    # Close the sidebar before the 'after' shot so the imagery comparison is
    # symmetric with the 'before' shot (both panes show the full map).
    await page.evaluate(
        """() => {
            const s = document.getElementById('sidebar');
            if (s) s.classList.remove('open');
        }"""
    )
    # Wait for tiles to load — NAIP at z14 is heavy.
    await page.wait_for_timeout(5000)
    after = await page.screenshot(
        full_page=False, animations="disabled", timeout=60000
    )

    # Composite side-by-side via Pillow.
    from PIL import Image, ImageDraw, ImageFont
    import io
    bimg = Image.open(io.BytesIO(before))
    aimg = Image.open(io.BytesIO(after))
    gap = 8
    composite = Image.new(
        "RGB",
        (bimg.width + aimg.width + gap, max(bimg.height, aimg.height)),
        "white",
    )
    composite.paste(bimg, (0, 0))
    composite.paste(aimg, (bimg.width + gap, 0))
    # Lightweight labels so README readers know which side is which.
    try:
        draw = ImageDraw.Draw(composite)
        font = ImageFont.load_default()
        for x, label in ((12, "Basemap only"), (bimg.width + gap + 12, "+ NOAA NAIP")):
            draw.rectangle((x - 4, 8, x + 160, 30), fill="black")
            draw.text((x, 12), label, fill="white", font=font)
    except Exception:
        pass
    composite.save(GALLERY_DIR / "imagery-before-after.png")


SHOTS = {
    # name: (shot_fn, viewport, color_scheme)
    "3d-terrain":            (shot_3d_terrain,            VIEWPORT, "light"),
    "voice-search":          (shot_voice_search,          VIEWPORT, "light"),
    "public-lands":          (shot_public_lands,          VIEWPORT, "light"),
    # admin-config and setup-wizard both honor prefers-color-scheme; force
    # dark to match the README aesthetic + spec ('clean dark mode').
    "admin-pipeline":        (shot_admin_pipeline,        VIEWPORT, "dark"),
    "setup-wizard":          (shot_setup_wizard,          VIEWPORT, "dark"),
    "kmz-overlay":           (shot_kmz_overlay,           VIEWPORT, "light"),
    "imagery-before-after":  (shot_imagery_before_after,  VIEWPORT, "light"),
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
            shot_fn, viewport, color_scheme = SHOTS[name]
            # device_scale_factor=2 is desirable for crisp README shots, but on
            # the Pi 5 the combination of DEM raycasting + 2x rendering can
            # push screenshot() past its default 30s timeout. Use 1x for now;
            # bump to 2 once benchmarked.
            ctx = await browser.new_context(
                viewport=viewport,
                device_scale_factor=1,
                color_scheme=color_scheme,
            )
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
