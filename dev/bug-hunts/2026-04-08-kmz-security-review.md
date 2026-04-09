# Bug Hunt Report — KMZ Import Security Review

## Scope
Security-focused review of the KMZ import overhaul design spec (`docs/superpowers/specs/2026-04-08-kmz-import-overhaul-design.md`) and the current import implementation in `frontend/app.js` (lines 322-403 popup code, lines 1738-1803 import pipeline). Reviewed `frontend/vendor/togeojson.js` lines 230-251 for style/icon extraction. Focus areas: input validation, XSS via unsanitized HTML rendering, archive extraction, CORS, fetch-then-blob pattern, malware vectors.

## Bugs

### 1. Pre-existing XSS via unsanitized HTML rendering in KML description popups
**Location:** frontend/app.js:354-360
**Severity:** critical
**Evidence:** The current code detects HTML in `properties.description` via regex and then renders it as raw HTML using DOM element properties that bypass text escaping. KML files from untrusted sources can contain arbitrary markup including script tags, event handler attributes (onerror, onload), iframe elements, SVG with onload, and CSS-based data exfiltration (background-image URLs). The only mitigation is hiding broken images via onerror handlers on img elements (lines 357-360), which does not address any of these vectors.

**Impact:** A malicious KMZ file imported by the user executes arbitrary JavaScript in the application context. On this platform (AREDN mesh / Tailscale TLS), this could access GPS coordinates, route history, admin panel APIs, or any data visible to the frontend. Since the admin config panel is on the same origin (localhost:8097 via NGINX), an XSS payload could potentially reach admin endpoints.

**Spec status:** The spec acknowledges this at Section 5 "KML Content Sanitization" and flags it for review, but does not mandate a fix. **This must be fixed as part of the overhaul, not deferred.** The overhaul increases attack surface by encouraging import of untrusted KMZ files and adding fetch of external resources directed by those files.

**Recommended fix:** Sanitize HTML descriptions before rendering. Options:
1. **DOMPurify** (vendored, ~14KB minified): Best option. Allows safe HTML formatting while stripping scripts, event handlers, and dangerous elements. Battle-tested, widely used, handles edge cases a custom allowlist would miss.
2. **Strict allowlist:** Parse with DOMParser, walk the tree, only keep safe elements (p, br, b, i, em, strong, a with href validation, table/tr/td/th, ul/ol/li, img with src validation). Reject everything else.
3. **Always use textContent:** Simplest but loses formatting in legitimate KML descriptions that contain HTML tables and styled text.

DOMPurify is the recommended approach.

### 2. Popup icon img.src set to unsanitized URL from KML properties
**Location:** frontend/app.js:341
**Severity:** significant
**Evidence:** `iconImg.src = props.icon` directly assigns a URL extracted from KML to an image element's src attribute without any validation. While img elements don't execute JavaScript from their src, this still allows: (a) SSRF-like behavior — the browser sends a GET request to any URL the attacker specifies, potentially leaking the user's IP and probing internal services; (b) tracking pixels — the attacker learns when and where the file was opened.

The spec's Section 5 URL validation only applies to the new icon pipeline's fetch path. The existing popup icon code at line 341 is NOT going through that validation. Even with the spec's proposed popup icon removal for features with _iconId, the popup icon is retained for fallback features — meaning some unsanitized img.src assignments will persist.

**Impact:** Information leakage (user IP, access timing) to attacker-controlled servers. On a mesh network this is less concerning (no internet), but on Tailscale HTTPS deployments it's a real vector.

**Recommended fix:** Apply the same URL validation from Section 5 to props.icon before setting img.src. If validation fails, don't render the image.

### 3. Archive path traversal in JSZip file() lookup
**Location:** Spec Section 1, step 3b: zipArchive.file(href)
**Severity:** minor (client-side only)
**Evidence:** The spec says to look up KML icon hrefs as archive paths via zipArchive.file(href). A malicious KMZ could contain hrefs with path traversal sequences (dot-dot-slash, URL-encoded variants, or backslashes). JSZip's file() method matches on exact path strings and stores paths as-is from the ZIP directory, so traversal attempts typically return null. However, the spec should explicitly mandate path normalization: reject any href containing "..", absolute paths ("/"), or backslashes before passing to zip.file().

**Impact:** Low. Client-side JavaScript cannot read the filesystem via JSZip. Defense-in-depth concern only.

### 4. Blob URL memory leak in fetch-then-blob pattern
**Location:** Spec Section 1, step 3c
**Severity:** minor
**Evidence:** The spec says "Revoke the blob URL after image loads." But if Image.onload or Image.onerror doesn't fire (page navigation, mid-import abort), the blob URL is never revoked. With 50 icon fetches max and small icon sizes (< 500 bytes each), the leak is negligible per import but could accumulate across repeated import/remove cycles.

**Impact:** Negligible memory leak. Theoretical concern only.

**Recommended fix:** Track created blob URLs and revoke all of them in the pipeline's finally block.

## Design Concerns

### A. Content-Type validation and SVG-as-image
The spec validates Content-Type starts with "image/". SVG files (image/svg+xml) pass this check. SVGs can contain script elements, onload handlers, and foreignObject with arbitrary HTML. Loading an SVG via new Image() is safe (browser sandboxes SVG in image context), and the fetch-then-blob-URL pattern means the SVG is loaded as a blob (same-origin), not from the original URL. The risk is theoretical but the spec should explicitly note that image/svg+xml is allowed and safe in this pipeline because: (a) it goes through the Image decode path (sandboxed), (b) it gets rasterized to pixel data via getImageData(), (c) the SVG source is never injected into the DOM.

### B. navigator.onLine is unreliable
The offline short-circuit uses navigator.onLine. This property is notoriously unreliable — it may return true on a mesh network with no internet route, or false on a wired connection with a captive portal. The spec should treat this as a performance optimization (skip waiting for timeouts) rather than a security boundary. The URL validation and fetch timeouts are the real security layer.

### C. Decompression bomb via JSZip
The spec limits archive entries scanned to 100 and file size to 100MB compressed. But JSZip's loadAsync(file) reads the entire archive into memory before scanning. A 100MB KMZ that decompresses to multi-GB of XML could OOM the browser. The MAX_FILE_SIZE_REJECT at 100MB applies to the raw file, which for a highly compressible KML could be 10:1 ratio (1GB decompressed).

**Recommended mitigation:** Check the uncompressed size from the ZIP directory before extracting. JSZip exposes uncompressed size on entry objects. Add a MAX_KML_SIZE limit (e.g., 500MB) to prevent decompression bombs: `if (kmlFile._data.uncompressedSize > MAX_KML_SIZE) reject`.
