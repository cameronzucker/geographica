# Adversarial Review R2 — Scale / Performance

**Spec under review:** [docs/superpowers/specs/2026-04-24-ruler-design.md](../../docs/superpowers/specs/2026-04-24-ruler-design.md)
**Date:** 2026-04-24
**Agent:** cholla
**Attack angle:** scale / performance — tile-fetch math, Pi 5 memory budget, drag rendering thrash, sparkline thrash, concurrent-fetch sizing, AbortController + generation race, pathological inputs, geodesic interpolation drift, cache eviction.

---

## Summary

Two **CRITICAL** issues, six **MAJOR** issues, three **MINOR** issues. The spec's biggest problem is that **its elevation-decode formula is for the wrong encoding**: the existing pipeline ships AWS Terrarium-encoded tiles (verified: `frontend/app.js:325, 334` use `encoding: 'terrarium'`; `scripts/download_elevation.py:39` pulls `s3.amazonaws.com/elevation-tiles-prod/terrarium/`; mbtiles metadata `name=elevation_terrarium`), but spec §E.3 codes Mapbox Terrain-RGB. Every elevation reading would be off by ~10000 m and a wrong slope. The second critical issue is that the spec's "~9.5 m/px at AZ latitude" claim for z=12 is **mathematically wrong** — the actual figure is ~32 m/px, off by 3.4×. This in turn invalidates the 50-tile cap, the 200-sample logic, and the entire "Why z=12" justification.

---

## Findings

### F2.1 — CRITICAL — Wrong elevation decode formula (Mapbox Terrain-RGB vs AWS Terrarium)

**Severity:** CRITICAL — every elevation sample will be off by thousands of meters and the slope will be inverted-ish; entire elevation-profile feature would ship broken.

**Claim:** Spec §E.3 line 181-184 specifies:

```js
function elevationFromRGB(r, g, b) {
  return -10000 + ((r * 65536 + g * 256 + b) * 0.1);  // meters
}
```

That is the **Mapbox Terrain-RGB** decode. Geographica does not ship Mapbox tiles. Verified ground truth:

- `frontend/app.js:319-336` — both elevation sources declare `encoding: 'terrarium'`.
- `scripts/download_elevation.py:39` — `TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"`.
- `scripts/download_elevation.py:238` — metadata key writes `("name", "elevation_terrarium")`.
- mbtiles file at `/srv/geographica/data/elevation.mbtiles` (127 GB, z=0..14, 1.47M tiles): metadata `description = "Terrain-RGB elevation tiles (Terrarium encoding)"` (note the misleading description string — the format **name** is Terrarium, the description text accidentally hybridizes both names).

The correct AWS Terrarium decode is:

```js
function elevationFromRGB(r, g, b) {
  return (r * 256 + g + b / 256) - 32768;  // meters
}
```

Concrete impact for a real Phoenix-area pixel `(R=129, G=232, B=128)`:
- Mapbox formula: `-10000 + (129*65536 + 232*256 + 128) * 0.1 = -10000 + 845884.8 = ~835885 m` (clearly nonsense — Earth's tallest peak is 8849 m).
- Terrarium formula: `(129*256 + 232 + 128/256) - 32768 = (33024 + 232 + 0.5) - 32768 = 488.5 m` (matches Phoenix elevation of ~340-500 m).

The spec's worked decode would output garbage, but it would not crash — readouts would show "min: 825 km, max: 836 km, gain: 11 km" and so on, on a ~50 m hike. QA might flag this in manual testing, but it could also slip through if the tester only "looks reasonable" at the sparkline shape (Mapbox's larger numeric range produces qualitatively similar bumps).

**Recommendation:** Rewrite §E.3's `elevationFromRGB` to the Terrarium formula. Add a unit-test fixture pinned to a real `(R, G, B)` triple from the existing mbtiles whose decoded elevation matches a known ground point (USGS DEM cross-check). Add a sanity-clamp: `if (elev < -500 || elev > 9000) return null` — Terrarium's encoding accommodates -32768..+32767, but real DEM values outside CONUS bounds [-100, 4500] should be treated as "decode failure / NoData sentinel" defensively.

The pitfalls doc should add an entry about Terrarium-vs-Terrain-RGB confusion — it's a recurring foot-gun (the description string in our own mbtiles uses "Terrain-RGB" as a generic phrase, which is what likely confused the spec author).

---

### F2.2 — CRITICAL — "~9.5 m/px at AZ latitude" is wrong by 3.4×; z=12 is actually ~32 m/px

**Severity:** CRITICAL — invalidates the entire "Why z=12" justification, the 200-sample cap rationale, and the 50-tile cap math.

**Claim:** Spec §E.3 line 195 asserts:

> **Why z=12:** ~9.5 m/px at AZ latitude. 200 samples on a 50-mile path = ~400m spacing → oversampling source resolution, every sample reads a real pixel.

The actual values (computed):

| zoom | tile width @ lat 33.45 (AZ) | m/px |
|---|---|---|
| z=12 | 8.16 km | **31.9 m/px** |
| z=13 | 4.08 km | **15.9 m/px** |
| z=14 | 2.04 km | **7.97 m/px** |

The spec's "~9.5 m/px at AZ" matches z=14, not z=12. So either:
- (a) The spec wants ~9.5 m/px and should sample at **z=14** (which has full coverage in the 127 GB mbtiles — verified: 1,105,470 tiles at z=14), OR
- (b) The spec wants z=12 sampling and should advertise ~32 m/px instead.

The downstream consequences:

- **§E.3 step 1** says `numSamples = clamp(Math.floor(L_total / 50), 50, 200)` — "~50 m sample spacing." On a 50-mile (~80.5 km) path, that gives 200 samples (capped) → 400 m spacing, *which is **larger** than the 32 m/px source resolution at z=12, so we are **undersampling**, not oversampling*. The "every sample reads a real pixel" justification reverses on the actual numbers.
- **Nyquist concern at z=12:** with 32 m/px source and 50 m sample target, 1 sample-per-pixel happens at exactly ~32 m. The 50-m default already loses fine ridge features that fit in a single source pixel.
- **The 50-tile hard cap** (§E.3 step 6) translates to about 50 × 8.16 km = 408 km of axis-aligned path, or ~250 km (~155 miles) on a worst-case diagonal. The spec's manual checklist says "1000-mile path" should hit the cap (it would, by 5×), but a 200-mile path would also hit the cap, and the spec implies that's the rare "pathological" case.

**Recommendation:** Pick one and rewrite §E.3 consistently:
- Option A: stay at z=12 and re-justify with ~32 m/px ("good enough for a 80×250-px sparkline; 5x reduction in tile count vs z=14"). Tighten the 50-m sample spacing to ~50 m baseline but acknowledge fine-ridge undersampling.
- Option B: switch to z=14 sampling for ~9.5 m/px true-to-spec resolution. This costs **16× more tiles** for the same path (z=14 tile is 1/16 the area of z=12). A 50-mile path that needed ~10-20 tiles at z=12 would need ~160-320 tiles at z=14, blowing through the 50-tile cap.
- Option C (recommended): hybrid — sample at z=13 (~16 m/px at AZ, 4× tile count vs z=12). Rewrite the cap as a **bytes-budget** cap (e.g., "abort if cumulative tile bytes downloaded exceeds 12 MB compressed") rather than a tile-count cap, since path-length doesn't map cleanly to tile-count across diagonal vs axis-aligned cases.

In any case, the open-question §"Open questions for adversarial review" #2 ("Is z=12 the right sample zoom?") needs a real answer in v2 of the spec, not a deferral.

---

### F2.3 — MAJOR — 50-tile cap is geometry-blind; AZ-east-to-CO-west traverse hits the cap mid-path

**Severity:** MAJOR — common real-world AREDN antenna-pointing distance (Phoenix to Denver, ~600 mi) silently degrades to "no elevation profile" without warning.

**Claim:** §E.3 step 6: "50-tile hard cap on pathological inputs; samples beyond → null". Math:

- z=12 tile = ~8 km wide at AZ latitude.
- Worst-case diagonal-aligned path: each tile crossed adds at least 1 tile (often 2 for tile-corners). A 600-mile path along ~45° diagonal could touch 600 mi × 1.609 / 8 km × 1.4 ≈ ~170 tiles.
- Cap of 50 = first ~125 km of path covered, last 80% null.
- Spec says "first 50 tiles only; rest → null with notice" (§F line 215). That means the elevation profile shows the first chunk of path as a real curve, then abruptly turns to a flat dashed line — visually misleading (looks like the rest of the route is at sea level).

**Recommendation:**
- Cap should trigger an **early-exit error path**, not partial profile: "Path too long for elevation profile (would need NN tiles, max 50). Showing distance only." Don't render half a profile — it's worse than no profile.
- Or: when over cap, **subsample more aggressively** — drop sample count from 200 to 100 to 50 — and re-evaluate tile coverage. A 600-mile path at 50 samples ≈ ~19 km/sample; sampling fewer points still touches all the same tiles, so this doesn't actually help unless you also reduce the rule that "every sample reads a real pixel."
- Better: scale `numSamples` down so the unique-tile count fits in budget. Iterate: pick samples, count unique tiles, if > 50 reduce `numSamples` by half and retry. Stops at min 30 samples; if still over budget, error out.

---

### F2.4 — MAJOR — Tile cache decoded-pixel size understated; ImageBitmap retention can OOM a long session

**Severity:** MAJOR — within a single session, no problem. Across many sessions on a long-running tablet (per project ethos: field-use Pi 5 admin tablet often left open all day), memory creeps until tab evicted by browser.

**Claim:** §E.3 step 5: "Per-session in-memory tile cache (≈6 MB for 30 tiles)."

Math reality:
- 256×256 pixel data via `getImageData` is **always RGBA** in `Uint8ClampedArray`, regardless of whether the source PNG has alpha. So **256 KB per tile, not 192 KB**.
- 30 tiles × 256 KB = **7.68 MB**, not "≈6 MB." Off by 28%.
- If the cache stores the original `HTMLImageElement` or `ImageBitmap` objects (not just the decoded `Uint8ClampedArray`), the browser keeps a separate decoded backing store on the GPU side, plus the source `HTMLImageElement` bitmap retains a CPU-side decoded copy. **Worst case: 2× = ~512 KB/tile, 30 tiles = ~15 MB**, plus the canvas backing store (256 KB) per draw call.
- Spec doesn't say "discard the Image after `getImageData`, retain only the typed array" — implementer might naturally keep the Image to redraw into the canvas on cache hit, doubling the memory.
- Across 50 measurements over different geographies (no eviction policy in spec — §F2.9), with 30 unique tiles each, you reach **15 MB × 50 = 750 MB** in a degenerate case. A long-running tablet session blows past sensible browser-tab budgets.

**Recommendation:**
- Specify exactly what's cached: a `Map<key, Uint8Array>` of `(tx, ty) → Uint8Array(196608)` (RGB-only; the spec already only decodes RGB and we don't need alpha for a Terrarium decode). 192 KB/tile, no `Image`/`ImageBitmap` retained.
- After `getImageData` extracts the array, set `img.src = ''` and `img = null` and `canvas.width = canvas.height = 0` to release the canvas backing store.
- Update §E.3 step 5 numbers: "≈5.8 MB for 30 tiles, 9.6 MB for 50 tiles."
- Specify an LRU eviction policy with a hard cap (recommend 50 tiles = ~9.6 MB) so a session of many measurements doesn't grow unbounded — see F2.9.
- Add a memory-pressure unit test: mock `Image.onload` 100 times, verify cache size never exceeds cap.

---

### F2.5 — MAJOR — Drag-mousemove source.setData() at 60 fps with vertex-source re-emit will stutter on Pi 5

**Severity:** MAJOR — drag is the most-touched interaction in the edit model; if it stutters on a Pi 5 sunlight-readable tablet, the feature feels broken.

**Claim:** §D line 140: "`mousemove` updates `state.vertices[i]` and re-emits source data WITHOUT recomputing distances/bearings (avoids per-frame thrash)."

Issue: the spec re-emits **both** `ruler-line-source` (a single LineString rebuilt from all vertices) and `ruler-vertex-source` (FeatureCollection of N points) on every mousemove. On Pi 5 (Raspberry Pi 5 GPU is VideoCore VII — a low-power tile-based mobile GPU), MapLibre `source.setData()` does:

1. Synchronous JSON-encode of the GeoJSON feature/collection on the main thread (cost: ~O(N) per vertex).
2. `postMessage` to the worker thread for tiling — structured-clone copy of the GeoJSON.
3. Worker re-tiles the source (cost: even for a single line/multipoint, the cost is non-trivial because of internal vector-tile generation and projection).
4. `postMessage` back with tile data.
5. Repaint.

For a 50-vertex measurement at 60 fps mousemove, that's 50 × 60 = 3000 features/sec round-tripped through the worker. On a Pi 5, this often stutters at ~25-30 fps under benchmark — visible jank. Even at 10 vertices it's noticeable on touch where dragging starts/stops abruptly.

The spec already nods at this concern with the "avoids per-frame thrash" parenthetical for distance recompute, but doesn't apply the same logic to source re-emit.

**Recommendation:**
- Coalesce source updates with `requestAnimationFrame`. On `mousemove`, write to a "pending" vertex array; an rAF callback (single one queued at a time) does the actual `setData`. Caps to display refresh rate, not input event rate (which can fire 120+ Hz on some pointing devices).
- Even better: use a **separate "drag preview" source layer** holding ONLY the dragged vertex's adjacent line segments and the dragged vertex itself. The main source stays static during drag. On `mouseup`, copy the preview's coordinates into the main source and clear the preview. This isolates the per-frame work to 2 line segments + 1 point regardless of total vertex count.
- Specify the drag-preview source pattern in §D, and benchmark on a 50-vertex path at touch-drag speed to validate.
- Cite the existing pattern in `frontend/app.js` for nav route line — the existing route renderer already deals with similar issues; the drag-preview pattern is a known good in this codebase.

---

### F2.6 — MAJOR — Sparkline render during long-path sampling shows nothing → perceived freeze

**Severity:** MAJOR — UX failure for the "1000-mile path" manual checklist case explicitly listed in §Testing strategy.

**Claim:** §C line 113: "Elevation profile — visible when `vertices.length ≥ 2` AND sampling has completed." For a 50-mile path that takes ~500 ms to sample (50 unique tiles × 100 ms median PNG-decode-and-fetch over LAN), the user sees:
1. Click Finish.
2. Elevation section blank.
3. ...wait... wait...
4. Profile snaps in.

For a 200-mile path that hits the 50-tile cap, sampling can take 1-2 s. For a 1000-mile path: ~3-5 s. The spec doesn't address what the UI shows during that interval. The state machine (§B) doesn't have a "sampling" state — the user is in `editing` with no visible feedback. On a sunlight-readable field tablet, this looks like a freeze: no spinner, no skeleton, no progress text.

This is the same UX issue that drove the nav-pipeline async refresh redesign (per `dev/handoff_*_noaa_refresh_async.md`). Should not be repeated.

**Recommendation:**
- Add a `sampling` sub-state (or `state.elevationProfile = { status: 'sampling', tilesFetched: K, tilesTotal: N }`).
- Render a skeleton sparkline (gray blocks at sample positions) + tile-progress counter ("Loading elevation: 12/30 tiles") during sampling.
- After all tiles fetched / aborted, replace skeleton with real sparkline.
- Sample on `requestIdleCallback` chunks of 5-10 tiles so the main thread isn't blocked decoding 50 PNGs in a row.
- Document behavior in §F (edge cases): "while sampling, elevation section shows skeleton + counter; vertex selection / drag is still responsive."

---

### F2.7 — MAJOR — Concurrent fetch limit of 8 is wrong for HTTP/2 (Tailscale TLS) — should be unbounded; for HTTP/1.1 LAN — too high

**Severity:** MAJOR — measurable performance variance across the two transports project ethos cares about (LAN HTTP and Tailscale HTTPS).

**Claim:** §E.3 step 5: "Concurrent fetch limit: 8."

Reality (verified):
- `nginx/nginx.conf:2` — `listen 80;` (HTTP/1.1 only on plain LAN port). Browsers cap at **6** concurrent connections per origin per HTTP/1.1 RFC. Setting cap to 8 means 2 of every 8 will queue at the browser's TCP-pool layer — so effective parallelism is 6.
- `nginx/tls-include.conf:1` — `listen 443 ssl http2;` (HTTP/2 on Tailscale TLS). HTTP/2 multiplexes all requests over **one** connection; the "concurrent" limit there is effectively the server's `http2_max_concurrent_streams` (default 128 in nginx). Limiting to 8 is **artificially throttling** the Tailscale path by 16×.

Manual checklist line 257 says "HTTPS Tailscale + HTTP LAN: ruler works identically" — but with the 8-cap, the LAN path has a slight queue and the TLS path is throttled. They will behave noticeably differently if measured (Tailscale TLS round-trip is also slower, so absolute timing is similar, but starvation risk is asymmetric).

**Recommendation:**
- Detect the protocol via `performance.getEntriesByType('resource')` after first tile fetch (`nextHopProtocol === 'h2'`). If HTTP/2, raise the cap to 32 (still leaves headroom for other tabs and avoids hammering the worker thread). If HTTP/1.1, lower to 6 (matches browser-default and avoids queued slots that look "in-flight" but aren't).
- Or: pick a single value safe for both — **6** is the right answer (browser-pool limit on HTTP/1.1 and a safe-but-conservative on HTTP/2). Leave the comment "could go higher on HTTP/2; left conservative for predictability."
- Add a comment in §E.3 step 5 acknowledging the protocol-dependent reality, even if v1 picks one fixed number.

---

### F2.8 — MAJOR — AbortController + generation counter race: aborted fetch can still resolve before abort fires; pixel-decode then runs on stale state

**Severity:** MAJOR — silent data corruption in elevation profile when user clicks Clear mid-sample, then immediately starts a new measurement.

**Claim:** §E.3 step 7: "all fetches share a single `AbortController` per sampling run. `clear()` and any state mutation that supersedes the in-flight run aborts the controller; in-flight pixel-decode work checks a generation counter before mutating `state.elevationProfile`."

Race scenario:
1. Sampling run A in flight: 30 tile fetches, AbortController A.
2. User clicks Clear → `clear()` calls `controllerA.abort()`. Generation counter increments to 2.
3. **But fetch #17 has already completed and its `.then(blob => imageBitmap)` is queued in the microtask queue.** `AbortController.abort()` aborts pending network ops only — it does NOT cancel already-resolved promise chains. The `.then(...)` runs.
4. User starts new measurement, places vertices, clicks Finish. Sampling run B starts, AbortController B. Generation = 3.
5. The .then chain from run A's fetch #17 finally executes: `bitmap → canvas.drawImage → ctx.getImageData`. Reads pixels into the old `samples[]` array (which is still in scope via closure). Computes elevations.
6. Generation check: `if (gen !== currentGen) return` — fires correctly, prevents `state.elevationProfile` mutation. ✓

So the generation-counter check **does** prevent state mutation. However, three issues remain:

(a) **Wasted CPU and battery on the Pi 5 client tablet.** Up to ~30 PNG decodes can complete after abort. Each decode is ~5-10 ms. Total ~150-300 ms of useless work. Not catastrophic, but on a Pi 5 sunlight-readable tablet under solar load, every CPU ms matters.

(b) **Memory pressure during the race window.** The decoded ImageBitmap (or Uint8ClampedArray, depending on impl) is materialized in memory before the gen check fires. For 30 tiles = 7.68 MB allocated then dropped. A user who repeatedly Clears and re-measures (a normal workflow during route planning) could see a sawtooth memory pattern, not freed until GC sweeps.

(c) **The spec doesn't specify *where* the gen check happens.** "Before mutating `state.elevationProfile`" is one location, but if the gen check fires after pixel decode, we've still paid the cost. Better: gen check at **fetch onload** (skip the decode entirely if gen mismatched).

(d) **AbortController may be redundant if the caller is well-behaved**, but it's strictly necessary for the network layer — without it, fetches keep filling the browser's connection pool, slowing down run B's fetches. Keep it.

**Recommendation:**
- Add a check at the top of the `image.onload` callback: `if (gen !== currentGen) { return; }` — skip the decode entirely.
- Alternatively, use `fetch(url, { signal })` → `response.arrayBuffer()` → `decodeImageInWorker(buf)` and check signal.aborted at every chain step.
- Document in §E.3 step 7 explicitly: "The gen check is performed (i) at fetch onload before decode, (ii) after decode before pixel array store, (iii) after sample collection before `state.elevationProfile` mutation."

---

### F2.9 — MAJOR — No tile cache eviction policy → unbounded growth across many measurements

**Severity:** MAJOR — long-running session in field use accumulates tile cache without bound.

**Claim:** §E.3 step 5: "Per-session in-memory tile cache (≈6 MB for 30 tiles)." No eviction described.

Workflow: a route-planner does 30 measurements over a multi-county area in a single session. Each measurement covers different terrain. Average 20 unique tiles per measurement → 600 unique tiles cached = ~115 MB (RGBA) or ~115 MB (RGB-only). At 50 measurements, ~190 MB. Pi 5 has 16 GB but the browser tab isn't entitled to all of it.

Also: re-measurements over **the same** area do reuse cached tiles, which is good — but only if the cache key is `(z, x, y)`. Spec says "Group samples by `(tx, ty)`" so the cache likely keys on that, no z prefix. If implementation later switches sample zoom dynamically (per F2.2), no z in key = silent cache poisoning.

**Recommendation:**
- Specify cache key as `${z}/${x}/${y}` from day one.
- Specify LRU policy with hard cap. Recommend **50-tile cap = ~9.6 MB** (RGBA) or **64-tile cap = ~12 MB** (RGB-only). Round number, easy to test, generous enough that two consecutive measurements over adjacent geographies share the working set.
- Implement as `Map` (preserves insertion order in JS) with manual eviction: on cache full, `delete first key returned by .keys()`.
- Add unit test: 100 sequential cache adds → final size ≤ cap.

---

### F2.10 — MINOR — Linear segment-interpolation drifts from geodesic for long segments at high latitude

**Severity:** MINOR — within v1's stated CONUS coverage (lat 31.3-49.0), the drift is below the sample-spacing resolution and well below sparkline pixel resolution.

**Claim:** §E.3 step 2: "compute `[lng, lat]` via linear segment-interpolation."

Linear interp of (lng, lat) is **not** the same as geodesic interp of a point on the great circle. For a 100-km segment at lat 49 going E-W, the great-circle arc bows N by a few hundred meters. Linear interp puts the midpoint exactly halfway in (lng, lat); geodesic puts it slightly N (toward the great-circle bulge).

Concrete numbers:
- 50-km E-W segment at lat 33.45: drift is ~6 m at midpoint. Sample spacing is 50 m. Drift = 12% of sample spacing — below source resolution.
- 100-km E-W segment at lat 49.0: drift is ~25 m at midpoint. Sample spacing is 50 m. Drift = 50% of sample spacing — at threshold.
- 500-km E-W segment at lat 49.0: drift is ~625 m. Path renders as straight line (per §D — single line segment from V1 to V2 in Mercator), but elevation samples are off by 625 m perpendicular at midpoint.

For the 1000-mile-path test in the manual checklist (probably E-W at lat 33.45), drift at midpoint ~80 m. At 33% latitude, this matters less than at high latitudes.

The MapLibre line itself is rendered as a Mercator-straight line, not a great-circle line, so the elevation samples and the displayed line agree. This is the right behavior for v1: "show what's directly under the line on the map." Geodesic interp would show elevation samples drifting off the visible line — visually confusing.

**Recommendation:** No change for v1; document the trade-off explicitly in §E.3 step 2: "Linear interp matches MapLibre's rendered line (Mercator-straight), even though both diverge from a true great-circle path. For CONUS-scale paths, drift is well below sparkline resolution. If future v2 renders great-circle line segments (`turf.greatCircle`), interp must switch to geodesic to stay consistent."

---

### F2.11 — MINOR — Pathological inputs §F doesn't address: 200+ duplicate vertices, vertex on tile boundary

**Severity:** MINOR — easy to add, prevents weird crashes from creative test inputs.

**Claim:** §F covers many cases but not:

(a) **200 duplicate vertices at the same point** (e.g., user holds finger on screen while drawing mode is active and a buggy touch handler emits 200 touchstart events). `samplePath` → all distances zero → `numSamples = clamp(0, 50, 200) = 50` → 50 samples all at the same lng/lat. Tile cache is hit 50 times for one tile, decode runs once. Sparkline = flat line. Probably benign, but the §F1 handling for "single vertex" doesn't extend to duplicates.

(b) **Vertex pixel at exact tile boundary** (e.g., sample lat/lng maps to pixel at intra-tile y=255 or y=0). Because Terrarium tiles don't include 1-px overlap, a sample at the boundary may decode from the wrong tile due to floating-point rounding (`Math.floor((lat - tileTop)/pixelHeight)` can give 256 or -1 for boundary cases). Result: array out-of-bounds → undefined → null sample → unnecessary coverage gap.

(c) **`numSamples = 0` from a zero-distance path of multiple duplicate vertices** is mathematically `clamp(0, 50, 200) = 50` but the loop `for (i in 0..numSamples)` produces samples at f=0, f=1/49, ..., f=1 — all on the same point, fine. No infinite loop.

(d) **Single vertex bug:** `samplePath(vertices=[V1], 50)` — current spec doesn't define this; presumably never called because `vertices.length < 2` is the gate. But defensive code should handle it.

**Recommendation:**
- Add to §F:
  - "Path with all-duplicate vertices: distance = 0, no elevation profile (vertices.length === 0 unique), banner says 'Path too short for elevation profile'."
  - "Sample at tile boundary: clamp pixel index to `[0, 255]` after `Math.floor`. Out-of-bounds = decode from in-bounds neighbor pixel, never undefined."
- Add unit tests: degenerate-duplicate path, tile-boundary sample.

---

### F2.12 — MINOR — Spec uses `_appAPI` to import `haversineDistance` but doesn't profile per-frame call count for drag

**Severity:** MINOR — performance optimization deferred.

**Claim:** §A line 54 — ruler.js consumes `haversineDistance` from `window._appAPI`. During drag-mousemove, even though the spec defers distance recompute to drag-end (§D line 140), the **sparkline doesn't get updated during drag** — it's stale until drag-end. UX is fine, but if a future version wants live distance during drag (which UX research often shows users want for "snap-to-distance" aids like "find a 5-mile loop"), the per-frame `haversineDistance` × N segments cost matters.

50 segments × 60 fps = 3000 haversines/sec. Each haversine is ~15 trig operations. On Pi 5 ARM JIT, ~3 µs each → 9 ms/sec for the math. Negligible vs MapLibre source-emit cost (F2.5).

**Recommendation:** No spec change for v1. Note in plan: "live drag distance is deferred; if added, profile at 50 vertices on Pi 5 hardware before shipping."

---

## Open questions resolved

- **Q1 (cancel in-flight fetches on drag):** Yes, but only if the spec changes drag-end to NOT immediately re-sample (which it does). Current spec has drag → drag-end → re-sample, and drag-end is the only re-sample trigger, so there's nothing in-flight to cancel during drag. *No spec change needed* once F2.6 (sampling sub-state) is addressed.

- **Q2 (z=12 right zoom):** **No** — see F2.2. Spec must pick z=12 OR z=14 explicitly; current "~9.5 m/px" claim is wrong for both.

- **Q3 (50-tile cap right):** **No** — see F2.3. Cap should drive an early-exit error, not a partial profile. And a bytes-budget cap (~12 MB) generalizes better than a tile-count cap.

- **Q4 (touch tap-vs-drag 200ms):** out of my lens (UX, not perf).

- **Q5 (banner stacking):** out of my lens.

- **Q6 (iOS Safari fetch throttling):** Real concern. iOS Safari caps to **6** concurrent fetches per origin under HTTP/1.1, same as desktop. Under HTTP/2 (Tailscale TLS), iOS Safari respects the server's `max_concurrent_streams`. Spec's "8" is wrong on HTTP/1.1. See F2.7.

- **Q7 (vertex list virtualization):** moot for performance — 50 DOM rows with 44px height is 2200 px scroll height, no problem. Don't virtualize.

- **Q8 (symbol layers + glyphs):** not my lens (style config), but worth flagging that sprite-glyph fonts must be served by the existing tileserver glyph endpoint. Verify before shipping.

---

## Recommended spec changes (priority order)

1. **CRITICAL:** Rewrite §E.3 `elevationFromRGB` to AWS Terrarium decode `(r * 256 + g + b/256) - 32768`. Add fixture-based unit test pinned to a known mbtiles tile.
2. **CRITICAL:** Resolve §E.3 z-level vs m/px contradiction. Pick z=12 (~32 m/px) or z=14 (~9.5 m/px), consistently. Recommend **z=12 + bytes-budget cap** (~12 MB compressed = ~190 tiles real-world; covers any realistic CONUS path).
3. **MAJOR:** Replace tile-count cap with bytes-budget OR sample-count-down-then-error strategy (§F2.3).
4. **MAJOR:** Specify cache as `Map<"z/x/y", Uint8Array(196608)>` with LRU eviction at 50 tiles. Update memory claim in §E.3 step 5 to "≈9.6 MB at full LRU." (§F2.4, F2.9)
5. **MAJOR:** Replace drag-mousemove direct `setData` with rAF-coalesced update OR drag-preview source layer (§F2.5).
6. **MAJOR:** Add "sampling" sub-state with skeleton sparkline + tile counter (§F2.6).
7. **MAJOR:** Re-justify or change concurrent-fetch limit; default to **6** (HTTP/1.1-safe and HTTP/2-conservative). Note the protocol asymmetry. (§F2.7)
8. **MAJOR:** Specify gen-check happens at three points: fetch onload (pre-decode), post-decode, pre-state-mutate (§F2.8).
9. **MINOR:** Document linear-vs-geodesic interp trade-off in §E.3 step 2 (§F2.10).
10. **MINOR:** Add edge cases to §F: all-duplicate vertices, tile-boundary pixel clamping (§F2.11).

After these changes, plan can proceed.

---

Agent: cholla
