# Vendor Libraries

This directory holds vendored JavaScript and CSS libraries used by the Geographica frontend.
These files are **checked into git** — no installation step needed.

## Included Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| MapLibre GL JS | 5.21.1 | Map rendering engine |
| toGeoJSON | 0.16.2 | KML → GeoJSON conversion for import |
| JSZip | 3.10.1 | KMZ archive extraction |
| DOMPurify | — | HTML sanitization for KML descriptions |

## Updating Versions

To update a vendor library, download the new tarball directly from the npm
registry (no npm CLI needed):

```bash
cd frontend/vendor

# Example: update MapLibre GL JS
wget https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-5.21.1.tgz
tar -xf maplibre-gl-5.21.1.tgz
cp package/dist/maplibre-gl.js . && cp package/dist/maplibre-gl.css .
rm -rf package maplibre-gl-5.21.1.tgz

cd ../..
git add frontend/vendor/ && git commit -m "chore: update maplibre-gl to X.Y.Z"
```
