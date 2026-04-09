# Security Review — Public Lands Layer Pipeline & Frontend

**Date:** 2026-04-09
**Reviewer:** CSO review (automated)
**Scope:** Design spec `docs/superpowers/specs/2026-04-09-public-lands-layer-design.md` — data download, ogr2ogr pipeline, Tippecanoe processing, TileServer GL serving, MapLibre frontend rendering, click popup content.
**Attack surface context:** Unlike the KMZ import overhaul (untrusted user uploads), this pipeline processes a single dataset from a known US government source (USGS ScienceBase). The pipeline runs on the host as root. No user-uploaded data enters this path.

## Overall Assessment

**Risk level: LOW.** The attack surface is meaningfully smaller than the KMZ import pipeline. The data source is a US government agency (USGS), downloaded once during setup, not at runtime. There are no user-supplied inputs beyond CLI arguments. The spec makes reasonable architectural choices. Three findings warrant attention, one moderate and two minor.

## Findings

### 1. Shell injection via detected layer name in ogr2ogr SQL

**Severity:** Moderate
**Location:** Spec Section 1, step 2-3 — auto-detected layer name interpolated into ogr2ogr command

**Evidence:** The pipeline auto-detects the GeoPackage layer name via `ogrinfo` pattern matching, then interpolates it into the ogr2ogr `-sql` argument as `FROM {detected_layer}`. If a modified GeoPackage contains a layer name with shell metacharacters, and the command is constructed via string formatting passed to a shell-mode subprocess call, this becomes a shell injection vector.

**Likelihood:** Very low. The GeoPackage comes from USGS over HTTPS. An attacker would need to MITM the download (difficult with TLS) or replace the cached file on disk (requires host access, at which point they already have root). However, the pipeline runs as root, so the blast radius of any injection is total.

**Recommendation:** The implementation MUST:
1. Use `subprocess.run([...], shell=False)` with the SQL string as a single list element, not interpolated into a shell command string. The existing pipeline scripts (`acquire_imagery.py`, `build_osm_pois.py`) correctly use list-form subprocess calls — follow that pattern.
2. Validate the detected layer name against a strict allowlist regex: `^[A-Za-z0-9_]+$`. PAD-US layer names are alphanumeric with underscores. Reject anything else.
3. Never use shell-mode subprocess invocation for any ogr2ogr/tippecanoe call.

**Note:** The spec's ogr2ogr command uses `{detected_layer}` inside a `-sql` argument. Since `-sql` is a single argument to ogr2ogr (not a shell command), passing it via `subprocess.run(['ogr2ogr', ..., '-sql', sql_string], shell=False)` means the layer name is confined to OGR's SQL parser, not the shell. OGR SQL is a limited dialect that cannot execute system commands. This is safe IF `shell=False` is used.

### 2. Download URL not pinned to HTTPS

**Severity:** Minor
**Location:** Spec Section 1, step 1 — `--padus-url` argument

**Evidence:** The spec allows overriding the download URL via `--padus-url`. If a user passes an HTTP URL (or if a future default URL change drops the S), the 2GB download would be vulnerable to MITM injection of a crafted GeoPackage. The default USGS ScienceBase URL uses HTTPS, but the spec does not mandate HTTPS enforcement.

**Likelihood:** Very low. The default URL is HTTPS. Override is a power-user CLI flag.

**Recommendation:** Validate that `--padus-url` starts with `https://`. Reject HTTP URLs with a clear error message. If there is a legitimate need for HTTP (local mirror), require a `--allow-insecure` flag to make the risk explicit.

### 3. Tippecanoe memory/disk exhaustion from crafted input

**Severity:** Minor
**Location:** Spec Section 1, step 5

**Evidence:** Tippecanoe processes the clipped GeoJSON. A crafted GeoJSON with extremely complex multipolygons (millions of vertices per feature) or enormous property strings could cause Tippecanoe to consume excessive memory or produce unexpectedly large MBTiles output. The `--maximum-tile-bytes=500000` flag limits individual tile size but not total output size or memory usage.

**Likelihood:** Very low. The input comes from ogr2ogr processing a USGS GeoPackage. An attacker would need to modify the intermediate GeoJSON file on disk between steps 3 and 5, which requires host access.

**Recommendation:** The spec already recommends stopping Docker services for memory headroom. Additionally:
1. Check intermediate GeoJSON file size before running Tippecanoe. If it exceeds an expected bound (e.g., 2GB for Western US), warn or abort.
2. Check final MBTiles size. The spec estimates 50-200MB. If it exceeds 500MB, warn.
These are sanity checks, not security boundaries.

### 4. Click popup XSS — NOT a concern

**Severity:** None (informational)
**Location:** Spec Section 3, click interaction

**Analysis:** The spec describes popups showing `name`, `agency`, and `designation` from vector tile feature properties. The existing codebase consistently uses `textContent` for DOM text insertion (verified across all popup code in `frontend/app.js`). The only `innerHTML` usage is for KML descriptions, which goes through DOMPurify.

As long as the public lands popup implementation follows the established pattern of `element.textContent = props.name` (not `innerHTML`), there is no XSS vector. Even if a crafted GeoPackage contained `<script>alert(1)</script>` in a `Unit_Nm` field, `textContent` renders it as literal text.

**Recommendation:** The spec should explicitly state: "Render all property values via `textContent`, not `innerHTML`." This is already the codebase convention but worth calling out for a new feature.

### 5. Malicious GeoPackage property content

**Severity:** None (informational)
**Location:** End-to-end chain: GeoPackage -> ogr2ogr -> GeoJSON -> Tippecanoe -> MBTiles -> TileServer GL -> MapLibre -> popup

**Analysis:** Could a modified PAD-US GeoPackage with malicious strings in `Unit_Nm`, `Mang_Name`, or `Des_Tp` fields cause harm? Tracing the chain:
1. **ogr2ogr** reads the field, writes it to GeoJSON as a JSON string (properly escaped).
2. **Tippecanoe** reads the GeoJSON, encodes the string into protobuf vector tile format (binary, no interpretation).
3. **TileServer GL** serves the protobuf bytes as-is. No parsing or rendering.
4. **MapLibre** decodes the protobuf, exposes properties as JavaScript strings.
5. **Popup code** renders via `textContent` (if following convention) — safe.

No stage in this chain interprets property values as code. The only risk is at the final rendering step, which is controlled by the frontend code (see finding 4).

### 6. TileServer GL vector tile parsing

**Severity:** None (informational)
**Location:** TileServer GL serving `public-lands.mbtiles`

**Analysis:** Could malformed vector tiles in the MBTiles cause issues in TileServer GL or MapLibre? TileServer GL serves tiles as raw bytes from SQLite — it does not parse the protobuf content. MapLibre's protobuf decoder is well-tested but could theoretically crash on malformed input. However, the tiles are generated by Tippecanoe (a trusted tool processing trusted intermediate data), not by an attacker. The MBTiles file sits on the host filesystem with root-only write access.

**Recommendation:** No action needed. If the MBTiles file is compromised, the attacker already has root on the host.

## Comparison to KMZ Security Review

| Dimension | KMZ Import | Public Lands |
|-----------|-----------|--------------|
| Data source | Untrusted user uploads | USGS government dataset |
| Runtime vs build-time | Runtime (any time) | Build-time (once, during setup) |
| User-controlled input | Arbitrary KMZ files | CLI bbox/URL arguments |
| HTML rendering risk | Critical (KML descriptions) | None (textContent only) |
| Shell injection surface | None (client-side JS) | Moderate (ogr2ogr subprocess) |
| Network exposure | Fetch external icon URLs | Single HTTPS download |

## Summary

The public lands pipeline has a narrow, well-understood attack surface. The primary actionable finding is ensuring the ogr2ogr subprocess call uses list-form arguments (not shell interpolation) and validates the detected layer name — a straightforward defensive coding practice that the existing pipeline scripts already follow. The HTTPS-only download URL validation is good hygiene. All other attack vectors are theoretical and require prior host compromise.

No blocking issues. Proceed with implementation, incorporating the recommendations above.
