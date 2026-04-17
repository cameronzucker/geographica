# Data Integrity Adversarial Review: MBTiles Imagery Pipeline

**Date:** 2026-04-16
**Reviewer:** Claude Opus 4 (adversarial data integrity specialist)
**Files reviewed:**
- `scripts/rasterio_ops.py` (entire file, 931 lines)
- `scripts/acquire_imagery.py` (merge_mbtiles ~610-677, convert_batch_to_mbtiles ~812-851, pipeline ordering ~2190-2250)

---

## Critical Issues

### C1. Erosion after overview build creates zoom-level coverage gaps

**File:** `rasterio_ops.py:845-930` (erode_nodata_edges) + `acquire_imagery.py:2218-2236`
**What goes wrong:** The pipeline order is: build overviews -> erode -> inpaint. Erosion runs independently at each zoom level. An overview tile at z13 may be eroded because its composited content is <90% fill at an edge strip, while the four child tiles at z14 survive erosion because each individually has >90% fill at its own edges.

**Visual impact:** "Pop-in" artifact: zooming out to z13 shows basemap (eroded overview tile missing), zooming in to z14 shows imagery. The viewer renders a visible hole at low zoom that fills in when the user zooms in.

**How to verify:**
```sql
-- Find z14 tiles with no parent at z13
SELECT t14.tile_column, t14.tile_row
FROM tiles t14
WHERE t14.zoom_level = 14
  AND NOT EXISTS (
    SELECT 1 FROM tiles t13
    WHERE t13.zoom_level = 13
      AND t13.tile_column = t14.tile_column / 2
      AND t13.tile_row = t14.tile_row / 2
  );
```
Non-zero results after pipeline completion indicate orphaned base tiles with no overview parent.

**Recommended fix:** Run erosion at the base zoom only. Then rebuild overviews from the post-erosion base tiles. Or: erosion should walk zoom levels top-down and only erode an overview tile if ALL of its children are also eroded.

---

### C2. inpaint_nodata_pixels loads all tile blobs into memory at once

**File:** `rasterio_ops.py:804-806`
**What goes wrong:** `conn.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles").fetchall()` loads every tile's binary data into a Python list. For a large MBTiles with 50,000 tiles at ~50KB each, this is ~2.5 GB of memory. On a Pi 5 running 7 Docker services, this can trigger the OOM killer.

**Visual impact:** Pipeline crash during post-processing. The MBTiles is left without inpainting -- visible black seams at NAIP quad boundaries.

**How to verify:**
```bash
# Check tile count and estimate memory
sqlite3 data/imagery.mbtiles "SELECT COUNT(*), SUM(LENGTH(tile_data))/1024/1024 FROM tiles;"
```
If the total exceeds ~1 GB, OOM risk is real.

**Recommended fix:** Process tiles in batches using LIMIT/OFFSET or a scrolling cursor:
```python
cursor = conn.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles")
while batch := cursor.fetchmany(500):
    for z, x, y, data in batch:
        ...
```

---

### C3. Multiple JPEG re-encode cycles degrade edge tile quality

**File:** `acquire_imagery.py:610-677` (merge_mbtiles) + `rasterio_ops.py:826-831` (inpaint)
**What goes wrong:** Edge tiles at NAIP quad boundaries undergo up to 3 JPEG encode/decode cycles:
1. Initial render in `merge_to_mbtiles` (quality 85)
2. Composite in `merge_mbtiles` -- decode both tiles, composite, re-encode at quality 85
3. Inpainting in `inpaint_nodata_pixels` -- decode, modify, re-encode at quality 85

Each JPEG cycle introduces ~1-2% additional artifact accumulation. Interior tiles undergo only 1 cycle, creating a visible quality difference at quad boundaries.

**Visual impact:** Tile boundaries show increased JPEG blocking artifacts compared to interior tiles. Most visible on smooth textures (water, agricultural fields, roads).

**How to verify:** Export a boundary tile and an adjacent interior tile; compare JPEG artifact levels visually or via SSIM metric.

**Recommended fix:** Use PNG as the intermediate format for compositing/inpainting, then do a single final JPEG encode. Or: increase quality to 95 for re-encode operations to reduce cumulative degradation.

---

## High-Severity Issues

### H1. build_overviews `levels` parameter is dead code

**File:** `rasterio_ops.py:677-685`
**What goes wrong:** The `levels` parameter is used to compute a `target_zoom` via `current_zoom - int(math.log2(level))`, but this computed value is never used as a loop bound. The actual overview loop always iterates from `max_zoom - 1` down to 0 (or until no parent tiles exist). The `levels` parameter has no effect on behavior.

**Visual impact:** None directly -- more overview levels are generated than expected, which wastes time and disk space but doesn't corrupt data.

**How to verify:**
```python
# Call with different levels, observe same result
build_overviews(path, levels=[2])       # Expected: 1 overview level
build_overviews(path, levels=[2,4,8,16]) # Expected: 4 overview levels
# Both produce overviews down to zoom 0
```

**Recommended fix:** Either use the computed `target_zoom` as the loop bound, or remove the `levels` parameter entirely.

---

### H2. build_overviews skips existing tiles -- stale overviews after re-merge

**File:** `rasterio_ops.py:702-706`
**What goes wrong:** The overview builder checks `SELECT 1 FROM tiles WHERE zoom_level=z AND tile_column=tx AND tile_row=ty` and skips if the tile exists. If base tiles change (e.g., a new NAIP batch is merged into an existing MBTiles), the existing overview tiles are NOT regenerated. They show the old data.

**Visual impact:** After merging new data into an existing MBTiles, overview zoom levels show stale imagery. Zooming in shows new data, zooming out shows old data.

**How to verify:** Merge a batch, build overviews, merge a second batch that overlaps, build overviews again. Compare overview tiles before and after -- they should differ but won't.

**Recommended fix:** Delete overview tiles before rebuilding, or add a `force` parameter that skips the existence check.

---

### H3. Tiles with 40-50% nodata get aggressively inpainted into smeared blobs

**File:** `rasterio_ops.py:818`
**What goes wrong:** `inpaint_nodata_pixels` processes tiles with 1-50% nodata pixels (the `max_nodata_ratio=0.5` threshold). A tile with 49% nodata gets every black pixel filled via `distance_transform_edt` from the nearest valid pixel. For a tile that's half imagery (left side) and half black (right side), the right half becomes a smeared repeat of the left edge.

This tile may survive erosion if the valid half covers all four edge strips above 90% -- for example, if the imagery occupies the top-left 51% in an L-shape that touches all edges.

**Visual impact:** Smeared, blurry tiles at NAIP quad corners where diagonal coverage boundaries cross tile boundaries. Looks like a watercolor wash over half the tile.

**How to verify:**
```python
# Find tiles with high but sub-threshold nodata
for z, x, y, data in tiles:
    arr = decode(data)
    black_pct = np.all(arr[:3] <= 20, axis=0).mean()
    if 0.3 < black_pct < 0.5:
        print(f"Tile {z}/{x}/{y}: {black_pct:.1%} nodata -- will be aggressively inpainted")
```

**Recommended fix:** Lower `max_nodata_ratio` to 0.2 or 0.3, or add a maximum inpainting distance (e.g., 10 pixels) beyond which pixels stay black rather than getting smeared.

---

### H4. Overview downsampling uses stride-2 subsampling, not averaging

**File:** `rasterio_ops.py:741`
**What goes wrong:** `small = tile_arr[:, ::2, ::2][:, :half, :half]` takes every other pixel (nearest-neighbor downsampling). The comment on line 739 says "Downsample to half size using simple averaging" but the code does subsampling, not averaging.

**Visual impact:** Overview tiles show aliasing artifacts (Moire patterns) on high-frequency content like rooftops, fences, row crops. Average resampling would produce smoother, more representative overviews.

**How to verify:** Compare a stride-2 overview tile against a properly averaged one on a tile containing row crops or a grid pattern.

**Recommended fix:**
```python
# True 2x2 averaging
small = tile_arr.reshape(bands, TILE_SIZE//2, 2, TILE_SIZE//2, 2).mean(axis=(2, 4)).astype(np.uint8)
```

---

## Medium-Severity Issues

### M1. Compositing threshold=20 can falsely classify dark valid pixels as nodata

**File:** `acquire_imagery.py:656` and `rasterio_ops.py:814`
**What goes wrong:** `np.all(arr[:3] <= 20, axis=0)` treats any pixel where all three RGB bands are <= 20 as nodata. While JPEG artifacts from true black (0,0,0) typically stay in the 0-5 range, legitimate dark imagery pixels in deep shadows, water bodies, or forest canopy can have all bands <= 20.

**Visual impact:** At NAIP quad overlaps where both tiles contain dark imagery (shadow in a canyon), pixels from the existing tile's dark area get replaced by the new tile's data. This creates a subtle seam where the same shadow area shows slightly different brightness.

**How to verify:** Search for composited tiles where both src and dst had dark-but-valid pixels:
```python
# After merge, count tiles where compositing replaced dark-but-valid pixels
both_dark = (dst_arr[:3] <= 20).all(axis=0) & (src_arr[:3] > 5).any(axis=0)
```

**Recommended fix:** Lower threshold to 5-8 (JPEG artifacts rarely exceed this), or use a per-tile adaptive threshold based on the histogram.

---

### M2. Erosion only checks rectangular boundary, misses interior notches

**File:** `rasterio_ops.py:873-887`
**What goes wrong:** `erode_nodata_edges` finds boundary tiles using `MIN/MAX(tile_column)` and `MIN/MAX(tile_row)`, then only checks tiles in those four rows/columns. If coverage has an interior gap (a failed NAIP quad download), tiles adjacent to the gap are NOT checked for nodata.

**Visual impact:** Black rectangles visible in the interior of the imagery layer where a NAIP quad failed to download. Surrounding tiles that overlap the gap have partial black areas that aren't eroded or inpainted (if >50% black).

**How to verify:** Deliberately skip downloading one NAIP quad in the middle of a batch and inspect the resulting tiles.

**Recommended fix:** Check ALL tiles for nodata ratio, not just boundary tiles. Or: use a per-tile fill threshold regardless of position.

---

### M3. Inpainting at overview zoom levels uses different nearest neighbors than base zoom

**File:** `rasterio_ops.py:804-842`
**What goes wrong:** Inpainting runs on all zoom levels. At overview zoom z13, a nodata pixel that was a 5-pixel seam at z14 becomes a 2-3 pixel seam. The `distance_transform_edt` at z13 has fewer pixels to work with, so the "nearest valid pixel" may come from a different NAIP quad than at z14.

**Visual impact:** Subtle color shift when zooming in/out at NAIP quad boundaries. The seam color at z13 may slightly differ from z14.

**How to verify:** Compare the same geographic location at z13 and z14 at a quad boundary -- pixel colors should be consistent but may differ.

**Recommended fix:** Only inpaint at the base zoom level, then rebuild overviews from inpainted base tiles.

---

### M4. merge_to_mbtiles assumes all input files share the same CRS

**File:** `rasterio_ops.py:322-323`
**What goes wrong:** `first_crs = datasets[0].crs` is used for all subsequent operations. `rasterio_merge` does not reproject inputs to a common CRS -- it assumes they already match. If inputs have different CRSes (e.g., one in EPSG:4326, another in EPSG:3857), the merge silently produces misaligned data.

**Visual impact:** Tiles from mismatched-CRS inputs appear at wrong geographic positions. Could result in imagery shifted by thousands of meters.

**How to verify:** Pass two GeoTIFFs with different CRSes and inspect the output.

**Recommended fix:** Assert all inputs share the same CRS, or reproject to a common CRS before merging:
```python
crses = {ds.crs.to_epsg() for ds in datasets}
if len(crses) > 1:
    raise ValueError(f"Input files have mixed CRSes: {crses}")
```

---

## Low-Severity Issues

### L1. `_compute_zoom_range` uses equatorial degree-to-meter conversion at all latitudes

**File:** `rasterio_ops.py:420`
**What goes wrong:** `res_meters = res_x * 111320` assumes 1 degree = 111,320 meters, which is only true at the equator. At latitude 48 (Washington state), the true value is ~74,500 meters, causing max_zoom to be overestimated by ~0.6 levels.

**Visual impact:** Tiles rendered at slightly higher zoom than the source resolution supports -- minor oversampling, no data loss. Only affects non-Mercator inputs, which don't occur in the normal pipeline.

---

### L2. Integer truncation in `_read_tile_from_array` edge placement

**File:** `rasterio_ops.py:610-613`
**What goes wrong:** `int()` truncates toward zero rather than rounding. For edge tiles, `dst_row_start` and `dst_col_start` may be placed 1 pixel too high or too far left. This is a sub-pixel error at tile boundaries.

**Visual impact:** 1-pixel misalignment at the very edge of coverage, completely invisible at normal map zoom levels.

---

### L3. Exact tile boundary alignment generates one extra empty tile column/row

**File:** `rasterio_ops.py:455-456` via `_lonlat_to_tile`
**What goes wrong:** When the data bbox aligns exactly with a tile boundary, `int()` truncation causes the adjacent tile to be included. E.g., lon=0.0 maps to tile x=n/2 (the next tile) rather than x=n/2-1 (the current tile).

**Visual impact:** None -- the extra tiles are completely empty and caught by `_is_empty_tile`. Wastes a negligible amount of processing time.

---

### L4. merge_mbtiles silently swallows decode errors during compositing

**File:** `acquire_imagery.py:664-665`
**What goes wrong:** `except Exception: pass` during tile compositing means any error (corrupted JPEG, band count mismatch, memory error) is silently ignored. The existing tile is kept, which is safe, but the failure is invisible.

**Visual impact:** If a tile is genuinely corrupted, the compositing fails silently and the original (possibly partially correct) tile is retained.

**Recommended fix:** Log the exception at WARNING level instead of silently passing.

---

## Verified Correct

The following areas were checked and found to be correct:

1. **`_tile_bounds()` coordinate math** -- produces correct EPSG:3857 bounds for all zoom levels. Verified at z0, z1, z2 with known tile positions.

2. **TMS y-flip in `_rasterize_to_disk`** -- `tms_y = (2**zoom - 1) - ty` correctly converts slippy (y=0 north) to TMS (y=0 south).

3. **Overview child placement** -- `y_off = (1 - dy) * half` correctly maps TMS dy=0 (south) to image bottom and dy=1 (north) to image top.

4. **`_lonlat_to_tile()` hemisphere handling** -- Verified for northern hemisphere (Phoenix), southern hemisphere (Buenos Aires), equator, and near-polar latitudes.

5. **`rowcol()` argument order in `_read_tile_from_array`** -- `rowcol(transform, west, north)` correctly passes x then y, matching the rasterio `rowcol(transform, xs, ys)` signature.

6. **Bounds computation in `_rasterize_to_disk`** -- Correctly derives (left, bottom, right, top) from the affine transform and array shape.

7. **`_update_mbtiles_bounds` TMS-to-geographic conversion** -- Correctly uses TMS min_row for southern boundary and max_row for northern boundary.

8. **Pipeline ordering** -- Inpainting runs after all batches are merged, preventing cross-quad smearing from premature inpainting.

9. **`_bulk_import_tiles` filesystem-to-SQLite transfer** -- File naming matches TMS convention, reads and inserts correctly.

10. **SQLite integer division for overview grouping** -- `tile_column/2` and `tile_row/2` produce correct parent coordinates for non-negative TMS values.
