# Seed Bug Classes — v1

This file is versioned alongside the agent prompt so new bug classes
can be added as they surface without changing code.

## Input validation
- Trailing slash in file paths (stripped? accepted with `//`? error?)
- Leading whitespace or BOM (U+FEFF) in text inputs
- Doubled slashes in paths (`/srv//foo`)
- Unicode / emoji / non-ASCII in paths and field values
- Extremely long inputs (>4 KB)
- Empty strings, whitespace-only
- Path traversal (`/srv/../etc/passwd`)
- Null bytes (`\x00`) in inputs
- Relative paths where absolute expected
- Shell metacharacters (`;`, `$`, backticks) in strings that end up in bash

## Resilience
- Stale CSRF token after wizard restart (container_restart_wizard, then retry)
- Navigate backward then forward
- Double-click Next / Submit
- Refresh browser mid-step (page_reload at each step boundary)
- Two tabs open on the same wizard session
- Fill fields in reverse order (Next in Step 2 before Step 1 complete)
- Force-click a disabled button via page.evaluate-equivalent

## Validation feedback
- Silent swallow of errors (action appears to succeed but state didn't change)
- Unhelpful error copy ("error occurred")
- Raw Python tracebacks rendered in the UI
- Error banners that auto-dismiss before a user could read them
- Buttons whose label does not match their action

## Protocol / API (via api_request)
- Missing CSRF token on POST (csrf="skip")
- Stale CSRF token (csrf="old_token")
- Wrong Content-Type header
- Malformed JSON body (raw_body="{bad")
- Missing required field
- Extra unexpected field (rejected or silently ignored?)
- Huge payload (megabytes)
- Idempotency: POST /api/start twice in a row — second should reject cleanly

## Pipeline artifact scope
Requires pipeline-post-condition tooling that v1 does NOT have (flagged v2).
Listed here so future runs against a more-capable harness look for these:
- Silent over-download: pipeline downloads more artifacts than the user's
  bbox requires (e.g. all 11 western-state PBFs for a Phoenix-only bbox).
  Test shape: after osm_download emits step_start, verify the set of
  files under /srv/.../pbf/ matches _states_intersecting(bbox).
- Silent under-download: pipeline skips a required state for an edge-
  scraping bbox, then merge succeeds with missing coverage.
- Stale-artifact leakage: a prior run with a wider bbox left files on
  disk; a subsequent narrower-bbox run's glob-based merge pulls them in.

## Catalog refresh (NOAA)
Symptoms to probe once the NOAA CONUS expansion ships:
- **Catalog refresh returned fewer states than expected.** The symlink was
  swapped but the new snapshot's `entries{}` has fewer states than the prior
  snapshot. Likely cause: Azure listing got truncated (NextMarker issues,
  intermittent 5xx) but `refresh_catalog` committed the partial result anyway.
  Test shape: compare `len(snapshot.entries)` across consecutive snapshots; a
  >5% drop without a corresponding `status=truncated` refresh-log entry is a bug.
- **Tile-index URL pattern drift.** NOAA changes the zip-naming convention
  upstream. `refresh_catalog` HEAD-validates every candidate; all fail; catalog
  silently rebuilds with zero entries. Test shape: a successful refresh with
  `len(entries) == 0` is suspicious — compare against prior snapshot's entry count.
- **Stale symlink after rollback.** `noaa_naip_catalog.json` points at a snapshot
  file that has been pruned. `pin_catalog_snapshot` raises FileNotFoundError.
  Expected: actionable error surfaced in admin UI + CLI exit 1, not a raw
  Python traceback.
- **Lockfile held by dead PID.** Refresh process crashed mid-run; next user
  hits 409 "locked" forever. The force-unlock affordance must be discoverable
  from the refresh-log panel's 409 response.

## Already-known bug classes (don't re-discover these)
- Debian Trixie docker-buildx file-conflict in bootstrap.sh (FIXED 59f00b5)
- websockets missing from setup/requirements.txt (FIXED ef28cd8)
- OSM PBF corruption from wget -c without integrity check (FIXED 44c5ea6)
- CSRF token regenerated on uvicorn restart (FIXED 9325e93)
- Trailing slash in custom data path not normalized (FIXED 7bcf685)
- osm_download over-downloads states outside the user's bbox (FIXED 2026-04-20)

## Novel
Anything else that looks wrong. Always consider: does this match a real
beta-tester experience? Would a naive first-time user hit this?
