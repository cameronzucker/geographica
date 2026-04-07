# Vendor Libraries

This directory holds vendored JavaScript and CSS libraries used by the Geographica frontend.
These files are **not** checked into git. They are installed at deploy time.

## Required Libraries

### MapLibre GL JS v5.x

Provides the map rendering engine.

```bash
npm pack maplibre-gl@5.21.1
tar -xf maplibre-gl-*.tgz
cp package/dist/maplibre-gl.js vendor/
cp package/dist/maplibre-gl.css vendor/
rm -rf package maplibre-gl-*.tgz
```

### toGeoJSON

Converts KML documents to GeoJSON for the import feature.

```bash
npm pack @mapbox/togeojson@0.16.2
tar -xf mapbox-togeojson-*.tgz
cp package/togeojson.js vendor/
rm -rf package mapbox-togeojson-*.tgz
```

### JSZip

Extracts KMZ archives (which are ZIP files containing KML).

```bash
npm pack jszip@3.10.1
tar -xf jszip-*.tgz
cp package/dist/jszip.min.js vendor/
rm -rf package jszip-*.tgz
```

## Quick Setup (all at once)

```bash
cd frontend/vendor

npm pack maplibre-gl@5.21.1
tar -xf maplibre-gl-*.tgz
cp package/dist/maplibre-gl.js .
cp package/dist/maplibre-gl.css .
rm -rf package maplibre-gl-*.tgz

npm pack @mapbox/togeojson@0.16.2
tar -xf mapbox-togeojson-*.tgz
cp package/togeojson.js .
rm -rf package mapbox-togeojson-*.tgz

npm pack jszip@3.10.1
tar -xf jszip-*.tgz
cp package/dist/jszip.min.js .
rm -rf package jszip-*.tgz
```
