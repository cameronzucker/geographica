# M2M API Test Results

**Date:** 2026-04-08
**Tester:** Cameron Zucker + Claude
**Spec:** docs/superpowers/specs/2026-04-08-m2m-api-test-plan.md

## Phase 0: Environment

- GDAL version: 3.10.3
- Pipeline image: built successfully
- Connectivity to m2m.cr.usgs.gov: confirmed (404 on base URL = reachable)
- Disk space: 587 GB free on /srv/geographica/data/
- AREDN routing: no conflict (default route via eth0)

## Phase 1: Authentication

- Login: **pass** — API key received (100 chars, JWT format `eyJjaWQi...`)
- Logout: **pass**
- Token invalidation: **confirmed** — 403 on reuse after logout

## Phase 2: Scene Search

- Dataset alias: `naip`
- Scenes found: **8** for Tucson bbox (-110.98,32.20,-110.90,32.28)
- Scene keys present: `browse, cloudCover, displayId, entityId, hasCustomizedMetadata, metadata, options, orderingId, publishDate, selected, spatialBounds, spatialCoverage, temporalCoverage`
- Available product names: **`['Compressed', 'Full Resolution']`**
- GeoTIFF filter matched: **NO** — original filter looked for "geotiff"/"tif", but USGS now uses "Compressed" and "Full Resolution". Fixed in commit `0260bcc`.
- Product ID field: `id` (not `productId` as documented). Fixed in commit `66eb785`.
- `downloadApplication: "m2m"` rejected by API. Removed in commit `66eb785`.

## Phase 3: Full Pipeline

- GeoTIFFs downloaded: **4 files**, 268 MB each (1.07 GB total)
- All 4 were "Compressed" products (half of the 8 scenes had only "Full Resolution")
- Download time: 2 min 51 sec at concurrency 2
- MBTiles created: **yes** — `/data/test_m2m.mbtiles` (682 MB)
- Total tiles: **52,760**
- Zoom levels: z15 (168), z16 (644), z17 (2,484), z18 (9,936), z19 (39,528)
- MBTiles format: JPEG
- Pipeline state: completed
- Duration: ~2 hours total (3 min download + 110 min GDAL conversion + 5 min pyramids)

## Phase 4: Quality

- Resolution: z15-z19 (M2M) vs z0-z16 (direct mode) — M2M provides **3 additional zoom levels**
- Bounds: -111.0 to -110.875, 32.1875 to 32.3125 — correctly covers the Tucson test bbox
- Artifacts: none observed in metadata
- GeoTIFF CRS: original files are in UTM (NAIP standard), GDAL warps to EPSG:3857 for MBTiles

## API Quirks & Differences

1. **Product names changed**: "GeoTIFF" → "Full Resolution" and "Compressed" (no "GeoTIFF" in name)
2. **Product ID field**: `id` in download-options response (not `productId`)
3. **downloadApplication parameter**: "m2m" is no longer a valid value; omit the parameter
4. **Scene deduplication**: 8 scenes returned but only 4 unique download URLs (download-retrieve deduplicates automatically)
5. **Download speed**: All 4 URLs were immediately available (no polling needed for this small bbox)
6. **GDAL conversion time**: ~110 minutes for 4x 268MB GeoTIFFs on Pi 5 — CPU-bound on gdal_translate

## Code Changes Required

| Commit | Fix |
|--------|-----|
| `f3907cc` | Add SIGTERM handling, progress reporting, error exits to run_m2m() |
| `0260bcc` | Update product name filter: "Compressed"/"Full Resolution" + per-entity dedup |
| `66eb785` | Fix product ID field mapping (`id` not `productId`), remove `downloadApplication` |
