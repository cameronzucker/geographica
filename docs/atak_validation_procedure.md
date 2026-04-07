# ATAK Tile Source Validation Procedure

## Prerequisites
- Android device with ATAK installed (CivTAK or WinTAK)
- Geographica stack running and serving tiles (Phase 0 complete)
- Device on same network as the Pi (AREDN mesh or LAN)

## Step 1: Create the ATAK map source XML

Create a file named `geographica-imagery.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<customMapSource>
  <name>Geographica USGS Imagery</name>
  <minZoom>0</minZoom>
  <maxZoom>14</maxZoom>
  <tileType>jpg</tileType>
  <tileUpdate>None</tileUpdate>
  <url>http://GEOGRAPHICA_HOST:8093/tiles/data/imagery/{$z}/{$x}/{$y}.jpg</url>
  <backgroundColor>#000000</backgroundColor>
</customMapSource>
```

Replace `GEOGRAPHICA_HOST` with the Pi's IP address or hostname on the mesh.

Optionally create a vector basemap source:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<customMapSource>
  <name>Geographica OSM Basemap</name>
  <minZoom>0</minZoom>
  <maxZoom>14</maxZoom>
  <tileType>png</tileType>
  <tileUpdate>None</tileUpdate>
  <url>http://GEOGRAPHICA_HOST:8093/tiles/styles/positron/{$z}/{$x}/{$y}.png</url>
  <backgroundColor>#000000</backgroundColor>
</customMapSource>
```

## Step 2: Install on ATAK device

Option A (file copy):
1. Connect Android device via USB or file transfer
2. Copy XML files to `sdcard/atak/imagery/` directory
3. Restart ATAK

Option B (auto-generated endpoint — build this into Geographica):
1. Geographica serves XML at `http://GEOGRAPHICA_HOST:8093/atak/imagery.xml`
2. In ATAK: Map Manager → Import → enter URL → import

## Step 3: Verify in ATAK

1. Open ATAK
2. Tap the map layers icon (usually top-right)
3. Navigate to Map Manager → Mobile
4. Find "Geographica USGS Imagery" in the list
5. Enable the layer
6. Pan and zoom within the downloaded coverage area

## Validation checklist

- [ ] Tiles render correctly (no distortion, correct geolocation)
- [ ] Zoom levels 0-14 all render
- [ ] Tiles at coverage boundary show black/transparent (not errors)
- [ ] Pan performance is acceptable over mesh network
- [ ] Tile format (JPEG for imagery, PNG for vector raster) renders without artifacts
- [ ] ATAK's offline cache works (disconnect from network, tiles still visible)

## Troubleshooting

**Tiles don't appear:**
- Verify URL format: `curl http://GEOGRAPHICA_HOST:8093/tiles/data/imagery/10/200/400.jpg`
- Check TileServer GL tile endpoint paths: `curl http://GEOGRAPHICA_HOST:8093/tiles/data/southwest5.json`
- The `{$z}/{$x}/{$y}` placeholders in the XML must match TileServer GL's URL scheme exactly

**Tiles appear in wrong location:**
- Confirm projection is EPSG:3857 (Web Mercator) — both TileServer GL and ATAK expect this
- Check Y-axis convention (XYZ vs TMS — TMS inverts Y). TileServer GL serves XYZ by default.

**Tiles render but look wrong (color, quality):**
- Verify tileType matches actual format (jpg vs png)
- Check JPEG compression quality in MBTiles (TileServer GL serves whatever's in the MBTiles)

## References
- ATAK-Maps repository: https://github.com/joshuafuller/ATAK-Maps
- MOBAC XML format: https://deepwiki.com/joshuafuller/ATAK-Maps/3.2-tmsxyz-tile-services
- CivTAK offline imagery wiki: https://wiki.civtak.org/index.php?title=Offline_Imagery
- ATAK 5.3 User Manual: https://static1.squarespace.com/static/5404b7d2e4b0feb6e5d9636b/t/6756e0a435922f074199ba09/1733746857539/ATAK+5.3+Software+User+Manual.pdf
