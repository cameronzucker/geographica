# M2M API End-to-End Test Plan

**Date:** 2026-04-08
**Status:** Ready to execute (ERS approval received)
**Author:** Cameron Zucker + Claude
**Depends on:** Imagery pipeline (`scripts/acquire_imagery.py` — already written)

## Overview

Validate the existing `--mode m2m` code path in `acquire_imagery.py` using live USGS M2M API credentials. The M2M pipeline implementation is complete but has never been tested against the live API — it was written based on the M2M API documentation at `https://m2m.cr.usgs.gov/api/docs/json/` (requires ERS authentication).

This is a test plan, not a feature design. No new code is expected unless the API has drifted since the implementation was written.

## What's already built

The M2M pipeline in `scripts/acquire_imagery.py` (lines 489-742) implements:

1. **`m2m_login()`** — authenticate via `login-token` endpoint, receive API key
2. **`m2m_find_naip_dataset()`** — discover the NAIP dataset alias via `dataset-search`
3. **`m2m_scene_search()`** — find NAIP scenes covering a bbox via `scene-search` with pagination
4. **`m2m_get_download_urls()`** — request downloads via `download-options` → `download-request` → poll `download-retrieve`
5. **`run_m2m()`** — orchestrator: login → search → download GeoTIFFs → convert to MBTiles → logout

Supporting infrastructure:
- Retry logic with exponential backoff (3 retries)
- Rate limit handling (HTTP 429)
- SIGTERM graceful shutdown
- Pipeline state file for admin monitor
- Checkpoint file for resumable downloads
- Credential storage via `/admin/credentials` endpoint (but we will NOT use file-based storage for this test — credentials passed via environment variables only)

## Code gaps discovered during review

The adversarial review identified two significant gaps in the M2M code path that must be fixed before or during testing:

### 1. No SIGTERM handling in `run_m2m()`

The `run_direct()` mode checks `_cancel_requested` for graceful shutdown on `docker stop`, but `run_m2m()` does not. A `docker stop` will kill the M2M pipeline uncleanly with no state file update. **Fix during implementation:** Add `_cancel_requested` checks in the download loop within `run_m2m()`.

### 2. No pipeline state/progress reporting in `run_m2m()`

The `run_direct()` mode calls `update_progress()` so the admin monitor can track progress. `run_m2m()` never calls `write_pipeline_state()` or `update_progress()`. The admin panel will be blind to M2M job status. **Fix during implementation:** Add `update_progress()` calls at key stages: after login, after scene search (with scene count), during downloads (with progress), on completion/error.

### 3. Silent exit on zero results

`run_m2m()` returns silently with exit code 0 when no scenes or URLs are found. The pipeline state file remains in "running" status. **Fix:** Call `sys.exit(1)` and write error state when no data is found.

## Credential handling

**Credentials are NEVER written to any file.** They are passed exclusively via environment variables:

```bash
export USGS_M2M_USERNAME="<username>"
export USGS_M2M_TOKEN="<token>"
```

The script reads these via `os.environ.get()` as fallback when `--m2m-username` and `--m2m-token` CLI args are not provided. For this test, use environment variables to avoid credentials appearing in shell history via CLI args.

Note: The admin panel endpoint (`POST /admin/credentials`) does write credentials to `/data/.credentials.json` with 0600 permissions. The env-var-only approach described here is specific to this manual test. For production use via the pipeline orchestrator, credentials flow from the credential store.

## Test phases

### Phase 0: Environment & connectivity checks

Before attempting API authentication, verify the execution environment.

**Checklist:**
1. Verify GDAL is available: `gdalinfo --version`, `gdalbuildvrt --version`, `gdal_translate --version`. If not on host, all phases run via Docker pipeline container.
2. Build pipeline image if needed: `docker compose build pipeline`
3. Verify outbound connectivity to M2M API: `curl -s -o /dev/null -w '%{http_code}' https://m2m.cr.usgs.gov/api/api/json/stable/` — expect 200 or 401 (both confirm reachability)
4. Verify ERS account has M2M API access approved (not just ERS registration). The M2M access request is separate from standard ERS registration.
5. If AREDN mesh interface is active, verify it is not the default route — M2M requires internet connectivity
6. Check staging directory disk space: `df -h /srv/geographica/data/` — NAIP GeoTIFFs are 200MB-1GB each

### Phase 1: Authentication smoke test

Verify login and logout work with the live API.

**Test:** Minimal Python script that calls `m2m_login()` and `m2m_logout()` only. No downloads.

**Expected outcome:**
- `m2m_login()` returns an API key string
- `m2m_logout()` succeeds (or logs non-fatal warning)

**Failure modes:**
- Invalid credentials → `RuntimeError: M2M login-token returned no API key`
- Account not approved for M2M → error message from API
- API endpoint URL changed → connection error or unexpected response format

### Phase 2: Scene search validation

Verify scene search returns NAIP scenes for a known-covered area.

**Test bbox:** Small area near Tucson with guaranteed NAIP coverage:
```
--bbox "-110.98,32.20,-110.90,32.28"
```
This is ~8km × ~9km — enough to find scenes without downloading significant data.

**Expected outcome:**
- `m2m_find_naip_dataset()` returns a dataset alias string
- `m2m_scene_search()` returns a non-empty list of scenes
- Scene objects contain `entityId` fields

**Failure modes:**
- Dataset alias format changed → no datasets found
- Scene search response structure changed → empty results or KeyError
- Spatial filter format changed → API error

### Phase 3: Download pipeline test

Verify the full download pipeline with a single scene.

**Test:** Run the complete `--mode m2m` pipeline with the small Tucson bbox and limited concurrency:

```bash
python3 scripts/acquire_imagery.py \
  --mode m2m \
  --bbox "-110.98,32.20,-110.90,32.28" \
  --output /tmp/test_m2m_imagery.mbtiles \
  --staging /srv/geographica/data/m2m_staging \
  --concurrency 2
```

**Expected outcome:**
- Log ALL available product names from `download-options` before filtering by 'geotiff'. If the filter matches nothing, the logged product names enable diagnosis (USGS may have renamed products, e.g., to 'COG' for Cloud-Optimized GeoTIFF).
- Download options returns available GeoTIFF products
- Download request succeeds, polling returns URLs
- At least one GeoTIFF downloads successfully
- `convert_geotiffs_to_mbtiles()` produces a valid MBTiles file
- MBTiles file contains tiles with correct metadata

**Failure modes:**
- Download options response format changed → no downloadable products found
- Download request label/application format changed → API error
- Download polling timeout (1 hour max) → no URLs obtained
- GeoTIFF format changed → GDAL conversion failure
- MBTiles metadata missing or incorrect

### Phase 4: Quality validation

Compare M2M imagery against existing direct-mode tiles for the same area.

**Test:** Visual comparison of tiles from the test MBTiles against the existing `imagery.mbtiles` for the Tucson bbox.

**Expected outcome:**
- M2M imagery is higher resolution (NAIP source vs cached tile service)
- Georeferencing is correct (tiles align with basemap)
- No visible artifacts or corruption

### Phase 5: Document results

| Outcome | Action |
|---------|--------|
| All phases pass | Update TODOS.md to mark M2M as validated. Document any API quirks found. |
| Auth fails | Check credential format, ERS approval scope. Document error. |
| API drift (minor — field renamed) | Fix inline, add regression test for new format |
| API drift (moderate — response structure changed) | Create branch, fix, test, merge. Update this test plan. |
| API drift (major — auth model changed, endpoints removed) | Write new spec. This test plan is void. |
| Downloads work but quality is wrong | Document the issue, check GDAL conversion parameters. |

## Known risks

1. **API format drift.** The M2M code was written based on documentation but never tested live. Response field names or nesting could differ from what was documented.

2. **Rate limiting.** The M2M API has rate limits. The test uses `--concurrency 2` and a tiny bbox to minimize risk of hitting them.

3. **Download queue delays.** The M2M API queues download requests asynchronously. The `download-retrieve` polling loop waits up to 1 hour. For a single scene this should be fast, but could take minutes.

4. **GDAL dependency.** The `convert_geotiffs_to_mbtiles()` function shells out to `gdal_translate` and `gdalwarp`. These must be available in the execution environment (they are in the pipeline Docker container).

5. **Download URL expiry.** M2M download URLs are time-limited (typically valid for a few hours). The current code calls `m2m_logout()` before downloading files. If downloads take long enough for URLs to expire, they will fail with no way to re-authenticate. For the small test bbox this is unlikely, but for production-scale downloads, consider deferring logout until after downloads complete.

6. **Default concurrency too high for M2M.** The CLI default is `--concurrency 80`, appropriate for the direct tile scraping mode but dangerously aggressive for M2M API. Always use `--concurrency 2-5` for M2M. The implementation plan should add an M2M-specific concurrency cap.

## Execution environment

Run all phases via the Docker pipeline container — GDAL dependencies are guaranteed available there. The pipeline image must be built first: `docker compose build pipeline`

```bash
docker compose run --rm \
  -e USGS_M2M_USERNAME="$USGS_M2M_USERNAME" \
  -e USGS_M2M_TOKEN="$USGS_M2M_TOKEN" \
  pipeline python3 /scripts/acquire_imagery.py \
  --mode m2m \
  --bbox "-110.98,32.20,-110.90,32.28" \
  --output /data/test_m2m.mbtiles \
  --staging /data/m2m_staging \
  --concurrency 2
```

## Tests to add after validation

These tests are a **required deliverable**, not optional. M2M code changes cannot be merged without mock-based regression tests.

**`tests/test_m2m_api.py`** — Mock-based unit tests:
- `m2m_login()` with mocked HTTP response returns API key
- `m2m_scene_search()` pagination logic with mocked multi-page responses
- `m2m_get_download_urls()` polling logic with mocked available/requested states
- Error handling: 429 rate limit, expired token, malformed response
- Checkpoint/resume: simulate a download interruption and verify the pipeline resumes correctly from the checkpoint file

These tests use mocked HTTP responses (not live API calls) to prevent CI from requiring credentials or network access. The mock response formats are based on the actual responses observed during this validation.
