/* =====================================================================
   Geographica — Offline Mapping Frontend
   =====================================================================
   Vanilla JS application using MapLibre GL JS.
   No build step required; served as static files by NGINX.
   ===================================================================== */

(function () {
  'use strict';

  // =====================================================================
  //  CONSTANTS
  // =====================================================================

  var STYLES = {
    positron:   '/tiles/styles/positron/style.json',
    darkmatter: '/tiles/styles/darkmatter/style.json'
  };

  var DEFAULT_CENTER = [-111.9, 34.0]; // Southwest US
  var DEFAULT_ZOOM   = 6;

  var SEARCH_DEBOUNCE_MS = 300;
  var GPS_RECONNECT_MS   = 5000;

  var MAX_FILE_SIZE_WARN   = 10 * 1024 * 1024;  // 10 MB
  var MAX_FILE_SIZE_REJECT = 50 * 1024 * 1024;  // 50 MB

  // =====================================================================
  //  STATE
  // =====================================================================

  var map;                     // MapLibre GL map instance
  var currentStyle = 'positron';
  var searchMarker = null;     // marker for search results
  var searchPopup  = null;     // popup for search results
  var searchTimer  = null;     // debounce timer

  var routeStartCoords = null; // [lng, lat]
  var routeEndCoords   = null;
  var routeStartMarker = null;
  var routeEndMarker   = null;
  var routeWaypoints   = [];   // [{coords: [lng,lat], name: str, marker: Marker}]
  var lastRouteTrip    = null;  // stored for export

  var importedFiles = {};       // { fileId: { name, geojson, visible, folders: { name: visible }, features: { id: visible } } }
  var importCounter = 0;        // unique ID counter for imported files

  var gpsMarker  = null;       // MapLibre marker for GPS position
  var gpsWs      = null;       // WebSocket connection
  var gpsStale   = true;
  var gpsLastPos = null;       // last known [lng, lat] for center-on-GPS
  var gpsAccuracyMarker = null; // accuracy circle DOM element inside marker

  var useImperial = true;      // true = imperial (ft/mi), false = metric (m/km)
  var coordFormat = 'dd';      // 'dd' | 'dms' | 'maidenhead' | 'mgrs'

  // =====================================================================
  //  1. MAP INITIALIZATION
  // =====================================================================

  function initMap() {
    map = new maplibregl.Map({
      container: 'map',
      style: STYLES[currentStyle],
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: false
    });

    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
    var scaleUnit = useImperial ? 'imperial' : 'metric';
    map._scaleControl = new maplibregl.ScaleControl({ unit: scaleUnit });
    map.addControl(map._scaleControl, 'bottom-right');

    map.on('load', function () {
      // Add empty sources for optional overlay layers (imagery, hillshade, route, imports).
      // Actual data is attached when the user toggles them on.
      addPlaceholderSources();
    });
  }

  /**
   * Pre-register sources and layers that features will populate later.
   * Called once on initial style load and again after every style swap.
   */
  function addPlaceholderSources() {
    // --- Imagery raster overlay ---
    if (!map.getSource('imagery')) {
      map.addSource('imagery', {
        type: 'raster',
        tiles: ['/tiles/data/imagery/{z}/{x}/{y}.png'],
        tileSize: 256,
        maxzoom: 18
      });
    }
    if (!map.getLayer('imagery-layer')) {
      map.addLayer({
        id: 'imagery-layer',
        type: 'raster',
        source: 'imagery',
        layout: { visibility: 'none' },
        paint: { 'raster-opacity': 0.8 }
      });
    }

    // --- Elevation (used for both hillshade overlay and 3D terrain) ---
    if (!map.getSource('elevation')) {
      map.addSource('elevation', {
        type: 'raster-dem',
        tiles: ['/tiles/data/elevation/{z}/{x}/{y}.png'],
        tileSize: 256,
        maxzoom: 12,
        encoding: 'terrarium'
      });
    }
    if (!map.getLayer('hillshade-layer')) {
      map.addLayer({
        id: 'hillshade-layer',
        type: 'hillshade',
        source: 'elevation',
        layout: { visibility: 'none' },
        paint: {
          'hillshade-shadow-color': '#333',
          'hillshade-highlight-color': '#fff',
          'hillshade-exaggeration': 0.3
        }
      });
    }

    // --- GPS accuracy circle (geographic, scales with map) ---
    if (!map.getSource('gps-accuracy')) {
      map.addSource('gps-accuracy', {
        type: 'geojson',
        data: emptyGeoJSON()
      });
    }
    if (!map.getLayer('gps-accuracy-fill')) {
      map.addLayer({
        id: 'gps-accuracy-fill',
        type: 'fill',
        source: 'gps-accuracy',
        paint: {
          'fill-color': '#4285f4',
          'fill-opacity': 0.1
        }
      });
    }
    if (!map.getLayer('gps-accuracy-outline')) {
      map.addLayer({
        id: 'gps-accuracy-outline',
        type: 'line',
        source: 'gps-accuracy',
        paint: {
          'line-color': '#4285f4',
          'line-opacity': 0.3,
          'line-width': 1.5
        }
      });
    }

    // --- Route polyline ---
    if (!map.getSource('route')) {
      map.addSource('route', {
        type: 'geojson',
        data: emptyGeoJSON()
      });
    }
    if (!map.getLayer('route-line')) {
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route',
        layout: {
          'line-join': 'round',
          'line-cap': 'round'
        },
        paint: {
          'line-color': '#4285f4',
          'line-width': 5,
          'line-opacity': 0.85
        }
      });
    }

    // --- Imported KML/KMZ features ---
    // Uses data-driven styling to preserve KML colors/widths/opacity.
    // toGeoJSON maps KML styles to properties: stroke, stroke-width,
    // stroke-opacity, fill, fill-opacity, marker-color.
    // We read these per-feature, falling back to defaults when absent.
    var defaultColor = '#f38ba8';

    if (!map.getSource('imported')) {
      map.addSource('imported', {
        type: 'geojson',
        data: emptyGeoJSON()
      });
    }
    // Points
    if (!map.getLayer('imported-points')) {
      map.addLayer({
        id: 'imported-points',
        type: 'circle',
        source: 'imported',
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 7,
          'circle-color': ['coalesce', ['get', 'marker-color'], ['get', 'fill'], ['get', 'stroke'], defaultColor],
          'circle-stroke-color': '#fff',
          'circle-stroke-width': 2,
          'circle-opacity': ['coalesce', ['get', 'fill-opacity'], 1]
        }
      });
    }
    // Lines
    if (!map.getLayer('imported-lines')) {
      map.addLayer({
        id: 'imported-lines',
        type: 'line',
        source: 'imported',
        filter: ['==', '$type', 'LineString'],
        layout: {
          'line-join': 'round',
          'line-cap': 'round'
        },
        paint: {
          'line-color': ['coalesce', ['get', 'stroke'], defaultColor],
          'line-width': ['coalesce', ['get', 'stroke-width'], 3],
          'line-opacity': ['coalesce', ['get', 'stroke-opacity'], 1]
        }
      });
    }
    // Polygon fills
    if (!map.getLayer('imported-polygons')) {
      map.addLayer({
        id: 'imported-polygons',
        type: 'fill',
        source: 'imported',
        filter: ['==', '$type', 'Polygon'],
        paint: {
          'fill-color': ['coalesce', ['get', 'fill'], ['get', 'stroke'], defaultColor],
          'fill-opacity': ['coalesce', ['get', 'fill-opacity'], 0.3]
        }
      });
    }
    // Polygon outlines (separate layer for stroke-width control)
    if (!map.getLayer('imported-polygon-outlines')) {
      map.addLayer({
        id: 'imported-polygon-outlines',
        type: 'line',
        source: 'imported',
        filter: ['==', '$type', 'Polygon'],
        paint: {
          'line-color': ['coalesce', ['get', 'stroke'], ['get', 'fill'], defaultColor],
          'line-width': ['coalesce', ['get', 'stroke-width'], 2],
          'line-opacity': ['coalesce', ['get', 'stroke-opacity'], 1]
        }
      });
    }

    // --- Click handlers for imported features ---
    var importedLayers = ['imported-points', 'imported-lines', 'imported-polygons', 'imported-polygon-outlines'];

    importedLayers.forEach(function (layerId) {
      // Change cursor on hover
      map.on('mouseenter', layerId, function () {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', layerId, function () {
        map.getCanvas().style.cursor = '';
      });

      // Click to show popup with feature properties
      map.on('click', layerId, function (e) {
        if (!e.features || !e.features.length) return;

        var feature = e.features[0];
        var props   = feature.properties || {};
        var coords  = e.lngLat;

        // Build popup content from KML properties
        var content = document.createElement('div');

        if (props.name) {
          var title = document.createElement('h4');
          title.textContent = props.name;
          content.appendChild(title);
        }

        // Show KML icon as an image if available and reachable
        if (props.icon && typeof props.icon === 'string') {
          var iconImg = document.createElement('img');
          iconImg.src = props.icon;
          iconImg.style.maxWidth = '32px';
          iconImg.style.maxHeight = '32px';
          iconImg.style.marginBottom = '4px';
          // Hide if it fails to load (offline, broken URL)
          iconImg.onerror = function () { this.style.display = 'none'; };
          content.appendChild(iconImg);
        }

        if (props.description) {
          var desc = document.createElement('div');
          desc.className = 'kml-description';
          // KML descriptions may contain HTML — render as HTML but fix broken images
          if (/<[a-z][\s\S]*>/i.test(props.description)) {
            desc.innerHTML = props.description;
            // Hide any broken images within the description
            var imgs = desc.querySelectorAll('img');
            for (var ii = 0; ii < imgs.length; ii++) {
              imgs[ii].onerror = function () { this.style.display = 'none'; };
            }
          } else {
            desc.textContent = props.description;
          }
          content.appendChild(desc);
        }

        // Show user-facing properties, skip internal and style keys
        var skipKeys = {
          name: 1, description: 1, styleUrl: 1, styleHash: 1,
          styleMapHash: 1, stroke: 1, fill: 1, 'stroke-opacity': 1,
          'fill-opacity': 1, 'stroke-width': 1, icon: 1, 'marker-color': 1,
          'marker-size': 1, 'marker-symbol': 1,
          _importFileId: 1, _importFeatureId: 1, _folder: 1
        };
        var extras = [];
        Object.keys(props).forEach(function (key) {
          if (!skipKeys[key] && props[key] !== null && props[key] !== '' && !key.startsWith('_')) {
            extras.push(key + ': ' + props[key]);
          }
        });
        if (extras.length) {
          var meta = document.createElement('p');
          meta.style.fontSize = '11px';
          meta.style.color = '#888';
          meta.style.marginTop = '6px';
          meta.textContent = extras.join(' | ');
          content.appendChild(meta);
        }

        // If nothing to show, at least show coordinates
        if (!content.childNodes.length) {
          var coordP = document.createElement('p');
          coordP.textContent = coords.lat.toFixed(5) + ', ' + coords.lng.toFixed(5);
          content.appendChild(coordP);
        }

        new maplibregl.Popup({ maxWidth: '320px' })
          .setLngLat(coords)
          .setDOMContent(content)
          .addTo(map);
      });
    });
  }

  /** Helper: empty GeoJSON FeatureCollection */
  function emptyGeoJSON() {
    return { type: 'FeatureCollection', features: [] };
  }

  // =====================================================================
  //  2. LAYER CONTROLS
  // =====================================================================

  function initLayerControls() {
    // Basemap radio buttons
    var radios = document.querySelectorAll('input[name="basemap"]');
    radios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        currentStyle = this.value;
        map.setStyle(STYLES[currentStyle]);
        // Re-add overlay sources/layers after style swap
        map.once('style.load', function () {
          addPlaceholderSources();
          syncLayerVisibility();
        });
      });
    });

    // Imagery toggle
    var imageryCheckbox = document.getElementById('toggle-imagery');
    var opacityRow      = document.getElementById('imagery-opacity-row');
    imageryCheckbox.addEventListener('change', function () {
      setLayerVisibility('imagery-layer', this.checked);
      opacityRow.classList.toggle('visible', this.checked);
    });

    // Imagery opacity slider
    var opacitySlider = document.getElementById('imagery-opacity');
    var opacityLabel  = document.getElementById('imagery-opacity-value');
    opacitySlider.addEventListener('input', function () {
      var val = parseInt(this.value, 10);
      opacityLabel.textContent = val + '%';
      if (map.getLayer('imagery-layer')) {
        map.setPaintProperty('imagery-layer', 'raster-opacity', val / 100);
      }
    });

    // Hillshade toggle
    var hillshadeCheckbox = document.getElementById('toggle-hillshade');
    hillshadeCheckbox.addEventListener('change', function () {
      setLayerVisibility('hillshade-layer', this.checked);
    });

    // 3D terrain toggle + exaggeration slider
    var terrainCheckbox = document.getElementById('toggle-terrain');
    var terrainSlider = document.getElementById('terrain-exaggeration');
    var terrainLabel = document.getElementById('terrain-exaggeration-value');

    function applyTerrain() {
      if (!terrainCheckbox || !terrainCheckbox.checked) return;
      var val = parseFloat(terrainSlider.value) / 10;
      map.setTerrain({ source: 'elevation', exaggeration: val });
    }

    if (terrainCheckbox) {
      terrainCheckbox.addEventListener('change', function () {
        if (this.checked) {
          applyTerrain();
        } else {
          map.setTerrain(null);
        }
      });
    }

    if (terrainSlider) {
      terrainSlider.addEventListener('input', function () {
        var val = parseFloat(this.value) / 10;
        terrainLabel.textContent = val.toFixed(1) + 'x';
        applyTerrain();
      });
    }

    // Coordinate format toggle
    var coordRadios = document.querySelectorAll('input[name="coordfmt"]');
    coordRadios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        coordFormat = this.value;
        updateCameraStatus();
      });
    });

    // Unit system toggle (imperial / metric)
    var unitRadios = document.querySelectorAll('input[name="units"]');
    unitRadios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        useImperial = (this.value === 'imperial');

        // Update the MapLibre scale bar
        if (map._scaleControl) {
          map.removeControl(map._scaleControl);
        }
        var scaleUnit = useImperial ? 'imperial' : 'metric';
        map._scaleControl = new maplibregl.ScaleControl({ unit: scaleUnit });
        map.addControl(map._scaleControl, 'bottom-right');

        // Refresh status bar readouts immediately
        updateCameraStatus();
      });
    });
  }

  /** Set layer visibility safely */
  function setLayerVisibility(layerId, visible) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
    }
  }

  /** After a style swap, re-apply checkbox state to layers */
  function syncLayerVisibility() {
    var imagery   = document.getElementById('toggle-imagery').checked;
    var hillshade = document.getElementById('toggle-hillshade').checked;
    var terrainCb = document.getElementById('toggle-terrain');
    setLayerVisibility('imagery-layer', imagery);
    setLayerVisibility('hillshade-layer', hillshade);
    if (terrainCb && terrainCb.checked) {
      var exSlider = document.getElementById('terrain-exaggeration');
      var ex = exSlider ? parseFloat(exSlider.value) / 10 : 1.5;
      map.setTerrain({ source: 'elevation', exaggeration: ex });
    }
  }

  // =====================================================================
  //  3. SIDEBAR TABS
  // =====================================================================

  function initSidebarTabs() {
    var tabs   = document.querySelectorAll('.tab-btn');
    var panels = document.querySelectorAll('.panel');

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var target = this.dataset.panel;
        tabs.forEach(function (t) { t.classList.remove('active'); });
        panels.forEach(function (p) { p.classList.remove('active'); });
        this.classList.add('active');
        document.getElementById(target).classList.add('active');
      });
    });

    // Mobile sidebar toggle (hamburger menu)
    var sidebarToggle = document.getElementById('sidebar-toggle');
    var sidebar       = document.getElementById('sidebar');
    var overlay       = document.getElementById('sidebar-overlay');

    var searchContainer = document.getElementById('search-container');

    function setSidebarOpen(open) {
      if (open) {
        sidebar.classList.add('open');
        overlay.classList.add('open');
        if (searchContainer) searchContainer.classList.add('sidebar-open');
      } else {
        sidebar.classList.remove('open');
        overlay.classList.remove('open');
        if (searchContainer) searchContainer.classList.remove('sidebar-open');
      }
    }

    if (sidebarToggle) {
      sidebarToggle.addEventListener('click', function () {
        setSidebarOpen(!sidebar.classList.contains('open'));
      });
    }

    if (overlay) {
      overlay.addEventListener('click', function () {
        setSidebarOpen(false);
      });
    }

    // Center on GPS button
    var centerBtn = document.getElementById('center-gps-btn');
    if (centerBtn) {
      centerBtn.addEventListener('click', function () {
        if (gpsLastPos) {
          map.flyTo({ center: gpsLastPos, zoom: Math.max(map.getZoom(), 14) });
        }
      });
    }
  }

  // =====================================================================
  //  4. SEARCH
  // =====================================================================

  function initSearch() {
    var input   = document.getElementById('search-input');
    var results = document.getElementById('search-results');

    // Search only on Enter key — not live-as-you-type (database-intensive)
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        var query = input.value.trim();
        if (query.length >= 2) {
          performSearch(query);
        }
      }
      // Escape clears results
      if (e.key === 'Escape') {
        hideSearchResults();
      }
    });

    // Close results on outside click
    document.addEventListener('click', function (e) {
      if (!e.target.closest('#search-container')) {
        hideSearchResults();
      }
    });
  }

  function performSearch(query) {
    var url = '/search/search?q=' + encodeURIComponent(query) + '&limit=10';
    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        renderSearchResults(data.results || data);
      })
      .catch(function (err) {
        console.error('Search error:', err);
      });
  }

  function renderSearchResults(results) {
    var list = document.getElementById('search-results');
    // Clear previous results using safe DOM removal
    while (list.firstChild) {
      list.removeChild(list.firstChild);
    }

    if (!results || results.length === 0) {
      var emptyLi = document.createElement('li');
      emptyLi.textContent = 'No results found';
      list.appendChild(emptyLi);
      list.classList.add('visible');
      return;
    }

    results.forEach(function (item) {
      var li = document.createElement('li');
      var name = item.name || item.display_name || 'Unknown';
      var type = item.type || item.category || '';

      // Build content safely using DOM methods (no innerHTML)
      li.appendChild(document.createTextNode(name));
      if (type) {
        var typeSpan = document.createElement('span');
        typeSpan.className = 'result-type';
        typeSpan.textContent = type;
        li.appendChild(typeSpan);
      }

      li.addEventListener('click', function () {
        selectSearchResult(item);
      });
      list.appendChild(li);
    });

    list.classList.add('visible');
  }

  function selectSearchResult(item) {
    hideSearchResults();

    var lng = parseFloat(item.lon || item.longitude || item.lng);
    var lat = parseFloat(item.lat || item.latitude);
    if (isNaN(lng) || isNaN(lat)) return;

    map.flyTo({ center: [lng, lat], zoom: 14 });

    // Remove previous marker/popup
    if (searchMarker) searchMarker.remove();
    if (searchPopup) searchPopup.remove();

    var name = item.name || item.display_name || 'Result';
    var type = item.type || item.category || '';

    // Build popup content using safe DOM methods
    var popupContent = document.createElement('div');
    var h4 = document.createElement('h4');
    h4.textContent = name;
    popupContent.appendChild(h4);
    if (type) {
      var p = document.createElement('p');
      p.textContent = type;
      popupContent.appendChild(p);
    }

    searchPopup = new maplibregl.Popup({ offset: 25, closeOnClick: true })
      .setDOMContent(popupContent);

    searchMarker = new maplibregl.Marker({ color: '#f38ba8' })
      .setLngLat([lng, lat])
      .setPopup(searchPopup)
      .addTo(map);

    searchPopup.addTo(map);
  }

  function hideSearchResults() {
    document.getElementById('search-results').classList.remove('visible');
  }

  // =====================================================================
  //  5. ROUTING
  // =====================================================================

  function initRouting() {
    var startInput  = document.getElementById('route-start');
    var endInput    = document.getElementById('route-end');
    var getRouteBtn = document.getElementById('get-route-btn');
    var clearBtn    = document.getElementById('clear-route-btn');
    var exportBtn   = document.getElementById('export-route-btn');
    var addWpBtn    = document.getElementById('add-waypoint-btn');

    // Geocode start/end on Enter
    startInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') geocodeForRoute(startInput.value, 'start');
    });
    endInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') geocodeForRoute(endInput.value, 'end');
    });

    // GPS fill buttons
    document.querySelectorAll('.gps-fill-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!gpsLastPos || gpsStale) {
          alert('No GPS fix available');
          return;
        }
        var target = this.dataset.target;
        var lng = gpsLastPos[0];
        var lat = gpsLastPos[1];
        var label = formatDD(lat, 'NS') + ', ' + formatDD(lng, 'EW');
        if (target === 'start') {
          routeStartCoords = [lng, lat];
          placeRouteMarker('start', [lng, lat]);
          document.getElementById('route-start').value = 'GPS: ' + label;
        } else if (target === 'end') {
          routeEndCoords = [lng, lat];
          placeRouteMarker('end', [lng, lat]);
          document.getElementById('route-end').value = 'GPS: ' + label;
        }
      });
    });

    // Add waypoint button
    if (addWpBtn) {
      addWpBtn.addEventListener('click', function () {
        addWaypointRow();
      });
    }

    getRouteBtn.addEventListener('click', requestRoute);
    clearBtn.addEventListener('click', clearRoute);

    // Export / print directions
    if (exportBtn) {
      exportBtn.addEventListener('click', exportDirections);
    }

    // Map click: reverse geocode and offer to add as route point
    map.on('click', function (e) {
      // Don't fire if clicking on an existing feature layer
      var features = map.queryRenderedFeatures(e.point, {
        layers: ['imported-points', 'imported-lines', 'imported-polygons', 'imported-polygon-outlines']
      });
      if (features.length > 0) return;

      var lngLat = e.lngLat;
      reverseGeocodeAndShowPopup(lngLat.lng, lngLat.lat);
    });
  }

  // ── Waypoint management ──────────────────────────────────────────────

  function addWaypointRow(name, coords) {
    var container = document.getElementById('route-waypoints');
    var idx = routeWaypoints.length;

    var wpData = { coords: coords || null, name: name || '', marker: null };
    routeWaypoints.push(wpData);

    var row = document.createElement('div');
    row.className = 'waypoint-row';
    row.dataset.wpIndex = idx;

    var input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Stop ' + (idx + 1) + '...';
    input.value = name || '';
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        geocodeForRoute(input.value, 'waypoint', idx);
      }
    });

    var gpsBtn = document.createElement('button');
    gpsBtn.className = 'gps-fill-btn';
    gpsBtn.textContent = 'GPS';
    gpsBtn.title = 'Use GPS position';
    gpsBtn.addEventListener('click', function () {
      if (!gpsLastPos || gpsStale) { alert('No GPS fix'); return; }
      wpData.coords = [gpsLastPos[0], gpsLastPos[1]];
      var label = formatDD(gpsLastPos[1], 'NS') + ', ' + formatDD(gpsLastPos[0], 'EW');
      input.value = 'GPS: ' + label;
      wpData.name = input.value;
      placeWaypointMarker(idx);
    });

    var removeBtn = document.createElement('button');
    removeBtn.className = 'waypoint-remove';
    removeBtn.textContent = '×';
    removeBtn.addEventListener('click', function () {
      removeWaypoint(idx);
    });

    row.appendChild(input);
    row.appendChild(gpsBtn);
    row.appendChild(removeBtn);
    container.appendChild(row);

    if (coords) {
      placeWaypointMarker(idx);
    }
  }

  function removeWaypoint(idx) {
    if (routeWaypoints[idx] && routeWaypoints[idx].marker) {
      routeWaypoints[idx].marker.remove();
    }
    routeWaypoints.splice(idx, 1);
    rebuildWaypointUI();
  }

  function rebuildWaypointUI() {
    var container = document.getElementById('route-waypoints');
    while (container.firstChild) container.removeChild(container.firstChild);
    var saved = routeWaypoints.slice();
    routeWaypoints = [];
    saved.forEach(function (wp) {
      addWaypointRow(wp.name, wp.coords);
    });
  }

  function placeWaypointMarker(idx) {
    var wp = routeWaypoints[idx];
    if (!wp || !wp.coords) return;
    if (wp.marker) wp.marker.remove();
    wp.marker = new maplibregl.Marker({ color: '#f9e2af' })
      .setLngLat(wp.coords).addTo(map);
  }

  // ── Map click → reverse geocode popup ────────────────────────────────

  function reverseGeocodeAndShowPopup(lng, lat) {
    var url = '/nominatim/reverse?lat=' + lat + '&lon=' + lng + '&format=jsonv2';
    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        var name = data.display_name || (lat.toFixed(5) + ', ' + lng.toFixed(5));
        showMapClickPopup(lng, lat, name, data);
      })
      .catch(function () {
        showMapClickPopup(lng, lat, lat.toFixed(5) + ', ' + lng.toFixed(5), null);
      });
  }

  function showMapClickPopup(lng, lat, name, geocodeData) {
    var content = document.createElement('div');

    var title = document.createElement('h4');
    title.textContent = name.length > 60 ? name.substring(0, 60) + '...' : name;
    title.style.marginBottom = '8px';
    content.appendChild(title);

    // Coordinates in all formats
    var coordDiv = document.createElement('div');
    coordDiv.style.fontSize = '11px';
    coordDiv.style.fontFamily = 'monospace';
    coordDiv.style.marginBottom = '8px';
    coordDiv.style.color = '#666';
    coordDiv.innerHTML =
      formatDD(lat, 'NS') + ' ' + formatDD(lng, 'EW') + '<br>' +
      formatDMS(lat, 'NS') + ' ' + formatDMS(lng, 'EW') + '<br>' +
      'Grid: ' + latLonToMaidenhead(lat, lng, 8) + '<br>' +
      'MGRS: ' + latLonToMGRS(lat, lng);
    content.appendChild(coordDiv);

    // Action buttons
    var actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.gap = '4px';
    actions.style.flexWrap = 'wrap';

    function makeBtn(label, fn) {
      var b = document.createElement('button');
      b.textContent = label;
      b.style.cssText = 'font-size:11px;padding:3px 8px;border:1px solid #ccc;border-radius:4px;background:#f5f5f5;cursor:pointer;color:#333;';
      b.addEventListener('click', fn);
      return b;
    }

    actions.appendChild(makeBtn('Route from here', function () {
      routeStartCoords = [lng, lat];
      placeRouteMarker('start', [lng, lat]);
      document.getElementById('route-start').value = name.substring(0, 50);
      popup.remove();
    }));

    actions.appendChild(makeBtn('Route to here', function () {
      routeEndCoords = [lng, lat];
      placeRouteMarker('end', [lng, lat]);
      document.getElementById('route-end').value = name.substring(0, 50);
      popup.remove();
    }));

    actions.appendChild(makeBtn('Add as stop', function () {
      addWaypointRow(name.substring(0, 50), [lng, lat]);
      popup.remove();
    }));

    actions.appendChild(makeBtn('Copy coords', function () {
      var text = lat.toFixed(6) + ', ' + lng.toFixed(6);
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text);
        b.textContent = 'Copied!';
      }
    }));

    content.appendChild(actions);

    var popup = new maplibregl.Popup({ maxWidth: '340px' })
      .setLngLat([lng, lat])
      .setDOMContent(content)
      .addTo(map);
  }

  /**
   * Geocode a text query and store coordinates for routing.
   * @param {string} query - search text
   * @param {'start'|'end'|'waypoint'} which - which endpoint
   * @param {number} [wpIdx] - waypoint index (when which === 'waypoint')
   */
  function geocodeForRoute(query, which, wpIdx) {
    if (!query.trim()) return;
    var url = '/search/search?q=' + encodeURIComponent(query) + '&limit=1';
    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        var results = data.results || data;
        if (!results || results.length === 0) {
          alert('Location not found: ' + query);
          return;
        }
        var item = results[0];
        var lng  = parseFloat(item.lon || item.longitude || item.lng);
        var lat  = parseFloat(item.lat || item.latitude);
        if (isNaN(lng) || isNaN(lat)) return;
        var displayName = item.name || item.display_name || query;

        if (which === 'start') {
          routeStartCoords = [lng, lat];
          placeRouteMarker('start', [lng, lat]);
          document.getElementById('route-start').value = displayName;
        } else if (which === 'end') {
          routeEndCoords = [lng, lat];
          placeRouteMarker('end', [lng, lat]);
          document.getElementById('route-end').value = displayName;
        } else if (which === 'waypoint' && wpIdx !== undefined) {
          routeWaypoints[wpIdx].coords = [lng, lat];
          routeWaypoints[wpIdx].name = displayName;
          placeWaypointMarker(wpIdx);
          var rows = document.querySelectorAll('.waypoint-row');
          if (rows[wpIdx]) {
            rows[wpIdx].querySelector('input').value = displayName;
          }
        }
      })
      .catch(function (err) {
        console.error('Geocode error:', err);
      });
  }

  function placeRouteMarker(which, lngLat) {
    var color = which === 'start' ? '#a6e3a1' : '#f38ba8';
    if (which === 'start') {
      if (routeStartMarker) routeStartMarker.remove();
      routeStartMarker = new maplibregl.Marker({ color: color })
        .setLngLat(lngLat).addTo(map);
    } else {
      if (routeEndMarker) routeEndMarker.remove();
      routeEndMarker = new maplibregl.Marker({ color: color })
        .setLngLat(lngLat).addTo(map);
    }
  }

  /** Build Valhalla request and render the route. */
  function requestRoute() {
    if (!routeStartCoords || !routeEndCoords) {
      alert('Please set both start and end locations (press Enter in each field to geocode).');
      return;
    }

    var costing = document.getElementById('costing-model').value;
    var avoidHighways = document.getElementById('avoid-highways').checked;
    var avoidTolls    = document.getElementById('avoid-tolls').checked;
    var avoidFerries  = document.getElementById('avoid-ferries').checked;

    // Build Valhalla JSON body
    var costingOptions = {};
    if (costing === 'auto') {
      costingOptions.auto = {};
      if (avoidHighways) costingOptions.auto.use_highways = 0;
      if (avoidTolls)    costingOptions.auto.use_tolls = 0;
      if (avoidFerries)  costingOptions.auto.use_ferry = 0;
    } else if (costing === 'bicycle') {
      costingOptions.bicycle = {};
      if (avoidFerries) costingOptions.bicycle.use_ferry = 0;
    } else {
      costingOptions.pedestrian = {};
      if (avoidFerries) costingOptions.pedestrian.use_ferry = 0;
    }

    // Build locations: start + waypoints + end
    var locations = [
      { lat: routeStartCoords[1], lon: routeStartCoords[0] }
    ];
    routeWaypoints.forEach(function (wp) {
      if (wp.coords) {
        locations.push({ lat: wp.coords[1], lon: wp.coords[0], type: 'through' });
      }
    });
    locations.push({ lat: routeEndCoords[1], lon: routeEndCoords[0] });

    var body = {
      locations: locations,
      costing: costing,
      costing_options: costingOptions,
      directions_options: { units: useImperial ? 'miles' : 'kilometers' }
    };

    var btn = document.getElementById('get-route-btn');
    btn.disabled = true;
    btn.textContent = 'Calculating...';

    fetch('/valhalla/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        btn.disabled = false;
        btn.textContent = 'Get Route';

        if (data.trip) {
          lastRouteTrip = data.trip;
          renderRoute(data.trip);
          document.getElementById('export-route-btn').classList.remove('hidden');
        } else if (data.error) {
          alert('Routing error: ' + (data.error || 'Unknown error'));
        } else {
          alert('No route found.');
        }
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = 'Get Route';
        console.error('Route error:', err);
        alert('Routing request failed.');
      });
  }

  /**
   * Render a Valhalla trip response on the map and display directions.
   * @param {Object} trip - Valhalla trip object
   */
  function renderRoute(trip) {
    // Decode polyline from each leg and merge
    var allCoords = [];
    var allManeuvers = [];

    trip.legs.forEach(function (leg) {
      var coords = decodePolyline(leg.shape);
      allCoords = allCoords.concat(coords);
      if (leg.maneuvers) {
        allManeuvers = allManeuvers.concat(leg.maneuvers);
      }
    });

    // Update route source
    var geojson = {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: allCoords
      }
    };

    var source = map.getSource('route');
    if (source) {
      source.setData(geojson);
    }

    // Fit map to route bounds
    var bounds = allCoords.reduce(function (b, coord) {
      return b.extend(coord);
    }, new maplibregl.LngLatBounds(allCoords[0], allCoords[0]));

    map.fitBounds(bounds, { padding: 60 });

    // Show route summary
    var summary = trip.summary || {};
    var dist    = (summary.length || 0);
    var distStr = useImperial ? dist.toFixed(1) + ' mi' : dist.toFixed(1) + ' km';
    var timeSec = summary.time || 0;
    var hours   = Math.floor(timeSec / 3600);
    var minutes = Math.round((timeSec % 3600) / 60);
    var timeStr = hours > 0 ? hours + 'h ' + minutes + 'min' : minutes + ' min';

    var summaryEl = document.getElementById('route-summary');
    // Build summary using safe DOM methods
    while (summaryEl.firstChild) {
      summaryEl.removeChild(summaryEl.firstChild);
    }
    var strong = document.createElement('strong');
    strong.textContent = distStr;
    summaryEl.appendChild(strong);
    summaryEl.appendChild(document.createTextNode(' \u00B7 ' + timeStr));
    summaryEl.classList.remove('hidden');

    // Show turn-by-turn directions (safe DOM construction)
    var dirList = document.getElementById('route-directions');
    while (dirList.firstChild) {
      dirList.removeChild(dirList.firstChild);
    }
    allManeuvers.forEach(function (m) {
      var li = document.createElement('li');
      var instruction = m.instruction || m.verbal_pre_transition_instruction || '';
      if (m.length) {
        var unit = useImperial ? ' mi' : ' km';
        instruction += ' (' + m.length.toFixed(1) + unit + ')';
      }
      li.textContent = instruction;
      dirList.appendChild(li);
    });
  }

  function clearRoute() {
    var source = map.getSource('route');
    if (source) source.setData(emptyGeoJSON());

    if (routeStartMarker) { routeStartMarker.remove(); routeStartMarker = null; }
    if (routeEndMarker)   { routeEndMarker.remove();   routeEndMarker   = null; }
    routeWaypoints.forEach(function (wp) { if (wp.marker) wp.marker.remove(); });
    routeWaypoints = [];
    routeStartCoords = null;
    routeEndCoords   = null;
    lastRouteTrip    = null;

    document.getElementById('route-start').value = '';
    document.getElementById('route-end').value   = '';
    var wpContainer = document.getElementById('route-waypoints');
    while (wpContainer.firstChild) wpContainer.removeChild(wpContainer.firstChild);

    var summaryEl = document.getElementById('route-summary');
    summaryEl.classList.add('hidden');
    while (summaryEl.firstChild) summaryEl.removeChild(summaryEl.firstChild);
    var dirList = document.getElementById('route-directions');
    while (dirList.firstChild) dirList.removeChild(dirList.firstChild);
    document.getElementById('export-route-btn').classList.add('hidden');
  }

  // ── Export / print directions ────────────────────────────────────────

  function exportDirections() {
    if (!lastRouteTrip) return;

    var summary = lastRouteTrip.summary || {};
    var dist = summary.length || 0;
    var distStr = useImperial ? dist.toFixed(1) + ' mi' : dist.toFixed(1) + ' km';
    var timeSec = summary.time || 0;
    var hours = Math.floor(timeSec / 3600);
    var minutes = Math.round((timeSec % 3600) / 60);
    var timeStr = hours > 0 ? hours + 'h ' + minutes + 'min' : minutes + ' min';

    var startName = document.getElementById('route-start').value || 'Start';
    var endName = document.getElementById('route-end').value || 'End';

    var allManeuvers = [];
    lastRouteTrip.legs.forEach(function (leg) {
      if (leg.maneuvers) allManeuvers = allManeuvers.concat(leg.maneuvers);
    });

    var unit = useImperial ? ' mi' : ' km';

    // Build printable page using DOM methods
    var printWin = window.open('', '_blank');
    var doc = printWin.document;
    doc.title = 'Geographica Directions';

    var style = doc.createElement('style');
    style.textContent =
      'body{font-family:Arial,sans-serif;max-width:700px;margin:20px auto;color:#333}' +
      'h1{font-size:18px;margin-bottom:4px}' +
      '.summary{font-size:14px;color:#666;margin-bottom:16px}' +
      'ol{padding-left:20px}' +
      'li{padding:6px 0;border-bottom:1px solid #eee;font-size:13px;line-height:1.5}' +
      '.meta{font-size:11px;color:#999;margin-top:16px}' +
      '@media print{body{margin:0}}';
    doc.head.appendChild(style);

    var h1 = doc.createElement('h1');
    h1.textContent = 'Directions: ' + startName + ' \u2192 ' + endName;
    doc.body.appendChild(h1);

    var summaryDiv = doc.createElement('div');
    summaryDiv.className = 'summary';
    summaryDiv.textContent = distStr + ' \u00B7 ' + timeStr;
    doc.body.appendChild(summaryDiv);

    var ol = doc.createElement('ol');
    allManeuvers.forEach(function (m) {
      var li = doc.createElement('li');
      var instr = m.instruction || m.verbal_pre_transition_instruction || '';
      if (m.length) instr += ' (' + m.length.toFixed(1) + unit + ')';
      li.textContent = instr;
      ol.appendChild(li);
    });
    doc.body.appendChild(ol);

    var meta = doc.createElement('div');
    meta.className = 'meta';
    meta.textContent = 'Generated by Geographica \u00B7 ' + new Date().toLocaleString();
    doc.body.appendChild(meta);

    doc.close();
    printWin.focus();
    printWin.print();
  }

  /**
   * Decode a Valhalla encoded polyline (precision 6).
   * Returns array of [lng, lat] coordinate pairs.
   */
  function decodePolyline(encoded) {
    var coords = [];
    var index  = 0;
    var lat    = 0;
    var lng    = 0;

    while (index < encoded.length) {
      var shift  = 0;
      var result = 0;
      var byte;

      // Decode latitude
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20);
      lat += (result & 1) ? ~(result >> 1) : (result >> 1);

      // Decode longitude
      shift  = 0;
      result = 0;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20);
      lng += (result & 1) ? ~(result >> 1) : (result >> 1);

      // Valhalla uses precision 6
      coords.push([lng / 1e6, lat / 1e6]);
    }

    return coords;
  }

  // =====================================================================
  //  6. GPS POSITION (WebSocket)
  // =====================================================================

  function initGPS() {
    connectGPS();
  }

  function connectGPS() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = protocol + '//' + location.host + '/gps/ws';

    try {
      gpsWs = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('GPS WebSocket connection failed:', e);
      scheduleGPSReconnect();
      return;
    }

    gpsWs.onopen = function () {
      console.log('GPS WebSocket connected');
      document.getElementById('gps-badge').classList.remove('hidden');
    };

    gpsWs.onmessage = function (event) {
      try {
        var data = JSON.parse(event.data);
        updateGPSPosition(data);
      } catch (e) {
        console.warn('GPS parse error:', e);
      }
    };

    gpsWs.onclose = function () {
      console.log('GPS WebSocket closed');
      setGPSStale(true);
      scheduleGPSReconnect();
    };

    gpsWs.onerror = function () {
      console.warn('GPS WebSocket error');
      setGPSStale(true);
    };
  }

  function scheduleGPSReconnect() {
    setTimeout(function () {
      console.log('GPS: attempting reconnect...');
      connectGPS();
    }, GPS_RECONNECT_MS);
  }

  /**
   * Update the GPS marker position on the map.
   * @param {Object} data - { lat, lon, heading, speed, stale, accuracy }
   */
  function updateGPSPosition(data) {
    var lng = parseFloat(data.lon || data.lng || data.longitude);
    var lat = parseFloat(data.lat || data.latitude);

    if (isNaN(lng) || isNaN(lat)) return;

    var stale    = !!data.stale;
    var heading  = data.heading || data.bearing || 0;
    var accuracy = data.accuracy; // meters, may be null

    setGPSStale(stale);

    if (!stale) {
      gpsLastPos = [lng, lat];
      // Show center button once we have a fix
      document.getElementById('center-gps-btn').classList.remove('hidden');
    }

    // Create or update the GPS marker
    if (!gpsMarker) {
      var el = createGPSMarkerElement();
      gpsMarker = new maplibregl.Marker({ element: el })
        .setLngLat([lng, lat])
        .addTo(map);
    } else {
      gpsMarker.setLngLat([lng, lat]);
    }

    // Update heading arrow rotation
    var markerEl = gpsMarker.getElement();
    markerEl.className = 'gps-marker' + (stale ? ' stale' : '');
    markerEl.style.transform += ' rotate(' + heading + 'deg)';

    // Update accuracy circle (geographic layer, scales with map)
    updateAccuracyCircle(lat, lng, accuracy);

    // Update status bar GPS readout
    updateGPSStatus(lat, lng, data.alt, accuracy, data.fix || 0);

    // Update tooltip
    if (stale) {
      markerEl.title = 'GPS signal lost';
    } else {
      var accText = accuracy ? ' ±' + formatDistance(accuracy) : '';
      markerEl.title = 'GPS: ' + lat.toFixed(5) + ', ' + lng.toFixed(5) + accText;
    }

    document.getElementById('gps-badge').classList.remove('hidden');
  }

  /**
   * Update the GPS accuracy circle as a map layer (geographic coordinates).
   * Uses a GeoJSON polygon circle so it scales correctly with the map.
   */
  function updateAccuracyCircle(lat, lng, accuracyMeters) {
    if (!accuracyMeters || accuracyMeters <= 0 || gpsStale) {
      // Hide circle
      var src = map.getSource('gps-accuracy');
      if (src) src.setData(emptyGeoJSON());
      return;
    }

    // Create a GeoJSON circle polygon (64 points)
    var circle = createGeoJSONCircle([lng, lat], accuracyMeters);

    var src = map.getSource('gps-accuracy');
    if (src) {
      src.setData(circle);
    }
  }

  /**
   * Create a GeoJSON polygon approximating a circle.
   * @param {Array} center - [lng, lat]
   * @param {number} radiusMeters
   */
  function createGeoJSONCircle(center, radiusMeters) {
    var points = 64;
    var coords = [];
    var earthRadius = 6371000; // meters
    var lat = center[1] * Math.PI / 180;
    var lng = center[0] * Math.PI / 180;
    var d = radiusMeters / earthRadius;

    for (var i = 0; i <= points; i++) {
      var bearing = (i * 360 / points) * Math.PI / 180;
      var pLat = Math.asin(Math.sin(lat) * Math.cos(d) + Math.cos(lat) * Math.sin(d) * Math.cos(bearing));
      var pLng = lng + Math.atan2(Math.sin(bearing) * Math.sin(d) * Math.cos(lat),
                                   Math.cos(d) - Math.sin(lat) * Math.sin(pLat));
      coords.push([pLng * 180 / Math.PI, pLat * 180 / Math.PI]);
    }

    return {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [coords] }
    };
  }

  function createGPSMarkerElement() {
    var el = document.createElement('div');
    el.className = 'gps-marker';

    // Heading arrow
    var arrow = document.createElement('div');
    arrow.className = 'heading-arrow';
    el.appendChild(arrow);

    return el;
  }

  function setGPSStale(stale) {
    gpsStale = stale;
    var dot  = document.getElementById('gps-dot');
    var text = document.getElementById('gps-text');

    if (stale) {
      dot.classList.add('stale');
      text.textContent = 'GPS signal lost';
    } else {
      dot.classList.remove('stale');
      text.textContent = 'GPS';
    }
  }

  // =====================================================================
  //  7. KML / KMZ IMPORT
  // =====================================================================

  function initImport() {
    var dropZone  = document.getElementById('drop-zone');
    var fileInput = document.getElementById('file-input');

    // Drag & drop handlers
    dropZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', function () {
      dropZone.classList.remove('drag-over');
    });
    dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        handleImportFile(e.dataTransfer.files[0]);
      }
    });

    // File input handler
    fileInput.addEventListener('change', function () {
      if (this.files.length) {
        handleImportFile(this.files[0]);
        this.value = ''; // reset for re-import
      }
    });
  }

  /**
   * Process an imported KML or KMZ file.
   * @param {File} file
   */
  function handleImportFile(file) {
    var statusEl = document.getElementById('import-status');
    statusEl.classList.remove('hidden', 'success', 'error', 'warning');

    // File size checks
    if (file.size > MAX_FILE_SIZE_REJECT) {
      showImportStatus('File too large (>' + (MAX_FILE_SIZE_REJECT / 1024 / 1024) + ' MB). Import rejected.', 'error');
      return;
    }
    if (file.size > MAX_FILE_SIZE_WARN) {
      showImportStatus('Large file (' + (file.size / 1024 / 1024).toFixed(1) + ' MB). Processing may be slow...', 'warning');
    }

    var ext = file.name.split('.').pop().toLowerCase();

    if (ext === 'kmz') {
      importKMZ(file);
    } else if (ext === 'kml') {
      importKML(file);
    } else {
      showImportStatus('Unsupported file type. Please use .kml or .kmz files.', 'error');
    }
  }

  function importKML(file) {
    var reader = new FileReader();
    reader.onload = function (e) {
      try {
        var parser = new DOMParser();
        var kmlDoc = parser.parseFromString(e.target.result, 'text/xml');
        processKMLDoc(kmlDoc, file.name);
      } catch (err) {
        console.error('KML parse error:', err);
        showImportStatus('Failed to parse KML: ' + err.message, 'error');
      }
    };
    reader.readAsText(file);
  }

  function importKMZ(file) {
    if (typeof JSZip === 'undefined') {
      showImportStatus('JSZip library not loaded. Cannot extract KMZ.', 'error');
      return;
    }

    JSZip.loadAsync(file).then(function (zip) {
      var kmlFile = null;
      zip.forEach(function (path, entry) {
        if (path.match(/\.kml$/i) && !kmlFile) kmlFile = entry;
      });
      if (!kmlFile) {
        showImportStatus('No KML file found inside KMZ archive.', 'error');
        return;
      }
      return kmlFile.async('string');
    }).then(function (kmlText) {
      if (!kmlText) return;
      var parser = new DOMParser();
      var kmlDoc = parser.parseFromString(kmlText, 'text/xml');
      processKMLDoc(kmlDoc, file.name);
    }).catch(function (err) {
      console.error('KMZ extract error:', err);
      showImportStatus('Failed to extract KMZ: ' + err.message, 'error');
    });
  }

  /**
   * Parse KML document: extract folder structure, convert to GeoJSON,
   * tag features with folder names and unique IDs, register as a managed import.
   */
  function processKMLDoc(kmlDoc, filename) {
    if (typeof toGeoJSON === 'undefined') {
      showImportStatus('toGeoJSON library not loaded.', 'error');
      return;
    }

    // Build a lookup: placemark name → folder name by walking the KML DOM
    var folderMap = {};
    var folders = kmlDoc.getElementsByTagName('Folder');
    for (var i = 0; i < folders.length; i++) {
      var folderNameEl = folders[i].childNodes;
      var folderName = 'Ungrouped';
      for (var j = 0; j < folderNameEl.length; j++) {
        if (folderNameEl[j].nodeName === 'name' && folderNameEl[j].textContent) {
          folderName = folderNameEl[j].textContent;
          break;
        }
      }
      // Direct child placemarks of this folder
      var pms = folders[i].childNodes;
      for (var k = 0; k < pms.length; k++) {
        if (pms[k].nodeName === 'Placemark') {
          var pmName = '';
          for (var m = 0; m < pms[k].childNodes.length; m++) {
            if (pms[k].childNodes[m].nodeName === 'name') {
              pmName = pms[k].childNodes[m].textContent || '';
              break;
            }
          }
          // Use placemark index as fallback key
          folderMap['pm_' + Object.keys(folderMap).length] = { folder: folderName, name: pmName };
        }
      }
    }

    var geojson = toGeoJSON.kml(kmlDoc);
    if (!geojson.features || geojson.features.length === 0) {
      showImportStatus('No features found in ' + filename, 'warning');
      return;
    }

    // Assign unique IDs and folder names to features
    var fileId = 'import_' + (++importCounter);
    var folderEntries = Object.values(folderMap);
    var folderSet = {};

    geojson.features.forEach(function (f, idx) {
      f.properties = f.properties || {};
      f.properties._importFileId = fileId;
      f.properties._importFeatureId = fileId + '_f' + idx;
      // Match to folder by index (toGeoJSON preserves order)
      if (folderEntries[idx]) {
        f.properties._folder = folderEntries[idx].folder;
      } else {
        f.properties._folder = 'Ungrouped';
      }
      folderSet[f.properties._folder] = true;
    });

    // Register the import
    var featureVisibility = {};
    geojson.features.forEach(function (f) {
      featureVisibility[f.properties._importFeatureId] = true;
    });

    var folderVisibility = {};
    Object.keys(folderSet).forEach(function (fn) { folderVisibility[fn] = true; });

    importedFiles[fileId] = {
      name: filename,
      geojson: geojson,
      visible: true,
      folders: folderVisibility,
      features: featureVisibility
    };

    // Update map and UI
    updateImportedMapData();
    buildImportLayerUI();

    // Fit map to imported data
    var bounds = new maplibregl.LngLatBounds();
    geojson.features.forEach(function (f) {
      if (!f.geometry || !f.geometry.coordinates) return;
      addCoordsToBounds(bounds, f.geometry.coordinates, f.geometry.type);
    });
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 60 });

    showImportStatus(
      'Imported ' + geojson.features.length + ' feature(s) from ' + filename,
      'success'
    );
  }

  /**
   * Merge all visible features from all imported files into the map source.
   */
  function updateImportedMapData() {
    var allFeatures = [];
    Object.keys(importedFiles).forEach(function (fileId) {
      var entry = importedFiles[fileId];
      if (!entry.visible) return;
      entry.geojson.features.forEach(function (f) {
        var fId = f.properties._importFeatureId;
        var folder = f.properties._folder;
        if (entry.features[fId] && entry.folders[folder]) {
          allFeatures.push(f);
        }
      });
    });

    var merged = { type: 'FeatureCollection', features: allFeatures };
    var source = map.getSource('imported');
    if (source) source.setData(merged);
  }

  /**
   * Build the import layer management UI in the sidebar.
   */
  function buildImportLayerUI() {
    var container = document.getElementById('import-layers');
    while (container.firstChild) container.removeChild(container.firstChild);

    var fileIds = Object.keys(importedFiles);
    if (fileIds.length === 0) return;

    fileIds.forEach(function (fileId) {
      var entry = importedFiles[fileId];
      var group = document.createElement('div');
      group.className = 'import-file-group';

      // File header row
      var header = document.createElement('div');
      header.className = 'import-file-header';

      var headerLabel = document.createElement('label');
      var fileCheckbox = document.createElement('input');
      fileCheckbox.type = 'checkbox';
      fileCheckbox.checked = entry.visible;
      fileCheckbox.addEventListener('change', function () {
        entry.visible = this.checked;
        updateImportedMapData();
      });
      headerLabel.appendChild(fileCheckbox);
      headerLabel.appendChild(document.createTextNode(' ' + entry.name));
      header.appendChild(headerLabel);

      var actions = document.createElement('div');
      actions.className = 'import-file-actions';

      var zoomBtn = document.createElement('button');
      zoomBtn.textContent = 'Zoom';
      zoomBtn.addEventListener('click', function () {
        var bounds = new maplibregl.LngLatBounds();
        entry.geojson.features.forEach(function (f) {
          if (f.geometry && f.geometry.coordinates) {
            addCoordsToBounds(bounds, f.geometry.coordinates, f.geometry.type);
          }
        });
        if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 60 });
      });
      actions.appendChild(zoomBtn);

      var removeBtn = document.createElement('button');
      removeBtn.textContent = 'Remove';
      removeBtn.className = 'danger';
      removeBtn.addEventListener('click', function () {
        delete importedFiles[fileId];
        updateImportedMapData();
        buildImportLayerUI();
      });
      actions.appendChild(removeBtn);
      header.appendChild(actions);
      group.appendChild(header);

      // Group features by folder
      var folderNames = Object.keys(entry.folders);
      var hasFolders = folderNames.length > 1 || (folderNames.length === 1 && folderNames[0] !== 'Ungrouped');

      folderNames.forEach(function (folderName) {
        var folderFeatures = entry.geojson.features.filter(function (f) {
          return f.properties._folder === folderName;
        });
        if (folderFeatures.length === 0) return;

        var folderGroup = document.createElement('div');
        folderGroup.className = 'import-folder-group';

        // Folder header (only show if there are actual named folders)
        if (hasFolders) {
          var folderHeader = document.createElement('div');
          folderHeader.className = 'import-folder-header';

          var folderCb = document.createElement('input');
          folderCb.type = 'checkbox';
          folderCb.checked = entry.folders[folderName];
          folderCb.addEventListener('change', (function (fn) {
            return function () {
              entry.folders[fn] = this.checked;
              // Sync child feature checkboxes
              var childCbs = folderGroup.querySelectorAll('.import-feature-item input[type="checkbox"]');
              for (var i = 0; i < childCbs.length; i++) {
                childCbs[i].checked = this.checked;
              }
              folderFeatures.forEach(function (f) {
                entry.features[f.properties._importFeatureId] = entry.folders[fn];
              });
              updateImportedMapData();
            };
          })(folderName));
          folderHeader.appendChild(folderCb);
          folderHeader.appendChild(document.createTextNode(' ' + folderName + ' (' + folderFeatures.length + ')'));
          folderGroup.appendChild(folderHeader);
        }

        // Individual features
        var featureList = document.createElement('div');
        featureList.className = 'import-feature-list';

        folderFeatures.forEach(function (f) {
          var fId = f.properties._importFeatureId;
          var item = document.createElement('div');
          item.className = 'import-feature-item';

          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = entry.features[fId];
          cb.addEventListener('change', function () {
            entry.features[fId] = this.checked;
            updateImportedMapData();
          });
          item.appendChild(cb);

          // Color swatch from KML style
          var featureColor = f.properties['marker-color'] || f.properties.stroke || f.properties.fill || '#f38ba8';
          var swatch = document.createElement('span');
          swatch.style.display = 'inline-block';
          swatch.style.width = '8px';
          swatch.style.height = '8px';
          swatch.style.borderRadius = '50%';
          swatch.style.background = featureColor;
          swatch.style.flexShrink = '0';
          item.appendChild(swatch);

          var nameSpan = document.createElement('span');
          nameSpan.textContent = f.properties.name || 'Unnamed';
          nameSpan.style.flex = '1';
          nameSpan.style.overflow = 'hidden';
          nameSpan.style.textOverflow = 'ellipsis';
          nameSpan.style.whiteSpace = 'nowrap';
          item.appendChild(nameSpan);

          var typeSpan = document.createElement('span');
          typeSpan.className = 'import-feature-type';
          typeSpan.textContent = f.geometry ? f.geometry.type : '?';
          item.appendChild(typeSpan);

          // Click feature name to zoom to it
          nameSpan.addEventListener('click', function (e) {
            e.preventDefault();
            if (!f.geometry || !f.geometry.coordinates) return;
            var b = new maplibregl.LngLatBounds();
            addCoordsToBounds(b, f.geometry.coordinates, f.geometry.type);
            if (!b.isEmpty()) map.fitBounds(b, { padding: 80, maxZoom: 16 });
          });

          featureList.appendChild(item);
        });

        folderGroup.appendChild(featureList);
        group.appendChild(folderGroup);
      });

      container.appendChild(group);
    });
  }

  /**
   * Recursively add coordinates to a LngLatBounds.
   * Handles Point, LineString, Polygon, Multi* geometries.
   */
  function addCoordsToBounds(bounds, coords, type) {
    if (type === 'Point') {
      bounds.extend(coords);
    } else if (type === 'LineString' || type === 'MultiPoint') {
      coords.forEach(function (c) { bounds.extend(c); });
    } else if (type === 'Polygon' || type === 'MultiLineString') {
      coords.forEach(function (ring) {
        ring.forEach(function (c) { bounds.extend(c); });
      });
    } else if (type === 'MultiPolygon') {
      coords.forEach(function (poly) {
        poly.forEach(function (ring) {
          ring.forEach(function (c) { bounds.extend(c); });
        });
      });
    }
  }

  function showImportStatus(message, level) {
    var el = document.getElementById('import-status');
    el.textContent = message;
    el.className = level; // 'success', 'error', or 'warning'
  }

  // =====================================================================
  //  8. STATUS BAR (GPS + Camera readouts)
  // =====================================================================

  function initStatusBar() {
    // Update camera readout on every map move
    map.on('move', updateCameraStatus);
    map.on('zoom', updateCameraStatus);
    map.on('pitch', updateCameraStatus);
    updateCameraStatus();
  }

  function updateCameraStatus() {
    var center = map.getCenter();
    var zoom = map.getZoom();
    var pitch = map.getPitch();

    // Approximate eye altitude from zoom level
    // At zoom 0, altitude ≈ 35,200 km (full earth view)
    // Each zoom halves the altitude
    var altMeters = 35200000 / Math.pow(2, zoom);
    // Adjust for pitch — when tilted, the effective eye altitude is higher
    if (pitch > 0) {
      altMeters = altMeters / Math.cos(pitch * Math.PI / 180);
    }

    var altStr = formatAltitude(altMeters);
    var posStr = formatPosition(center.lat, center.lng);

    var el = document.getElementById('status-camera-value');
    if (el) {
      el.textContent = posStr + '  alt ' + altStr;
    }
  }

  /**
   * Update GPS position readout in the status bar.
   * Called from updateGPSPosition() on each WebSocket message.
   */
  function updateGPSStatus(lat, lng, alt, accuracy, fix) {
    var el = document.getElementById('status-gps-value');
    if (!el) return;

    if (fix < 2) {
      el.textContent = 'No fix';
      return;
    }

    var posStr = formatPosition(lat, lng);
    var altStr = alt ? formatAltitude(alt) : '—';
    var accStr = accuracy ? '±' + formatDistance(accuracy) : '';
    var fixStr = fix === 2 ? '2D' : '3D';

    el.textContent = posStr + '  ' + altStr + '  ' + accStr + '  ' + fixStr;
  }

  /**
   * Format a lat/lon pair according to the selected coordinate format.
   * Returns a single string for both coordinates.
   */
  function formatPosition(lat, lon) {
    switch (coordFormat) {
      case 'dms':   return formatDMS(lat, 'NS') + '  ' + formatDMS(lon, 'EW');
      case 'maidenhead': return latLonToMaidenhead(lat, lon, 8);
      case 'mgrs':  return latLonToMGRS(lat, lon);
      default:      return formatDD(lat, 'NS') + '  ' + formatDD(lon, 'EW');
    }
  }

  /** Decimal degrees: "33.65061° N" */
  function formatDD(value, dirs) {
    var abs = Math.abs(value);
    var dir = value >= 0 ? dirs[0] : dirs[1];
    return abs.toFixed(5) + '° ' + dir;
  }

  /** Degrees/minutes/seconds: "33° 39′ 02.2″ N" */
  function formatDMS(value, dirs) {
    var abs = Math.abs(value);
    var dir = value >= 0 ? dirs[0] : dirs[1];
    var d = Math.floor(abs);
    var mf = (abs - d) * 60;
    var m = Math.floor(mf);
    var s = (mf - m) * 60;
    return d + '° ' + pad2(m) + '′ ' + s.toFixed(1) + '″ ' + dir;
  }

  function pad2(n) { return n < 10 ? '0' + n : '' + n; }

  /**
   * Convert lat/lon to Maidenhead grid locator.
   * @param {number} lat - Latitude (-90 to 90)
   * @param {number} lon - Longitude (-180 to 180)
   * @param {number} precision - 4, 6, 8, or 10 characters (default 6)
   * @returns {string} e.g., "DM33wv73"
   */
  function latLonToMaidenhead(lat, lon, precision) {
    precision = precision || 6;
    var A = 'A'.charCodeAt(0);
    var a = 'a'.charCodeAt(0);

    // Normalize to positive range
    var Lon = lon + 180;
    var Lat = lat + 90;

    var grid = '';

    // Field (18 divisions, uppercase)
    grid += String.fromCharCode(A + Math.floor(Lon / 20));
    grid += String.fromCharCode(A + Math.floor(Lat / 10));
    Lon = Lon % 20;
    Lat = Lat % 10;

    // Square (10 divisions, digits)
    grid += Math.floor(Lon / 2);
    grid += Math.floor(Lat / 1);
    Lon = Lon % 2;
    Lat = Lat % 1;

    if (precision >= 6) {
      // Subsquare (24 divisions, lowercase)
      grid += String.fromCharCode(a + Math.floor(Lon / (2 / 24)));
      grid += String.fromCharCode(a + Math.floor(Lat / (1 / 24)));
      Lon = Lon % (2 / 24);
      Lat = Lat % (1 / 24);
    }

    if (precision >= 8) {
      // Extended square (10 divisions, digits)
      grid += Math.floor(Lon / (2 / 240));
      grid += Math.floor(Lat / (1 / 240));
    }

    return grid;
  }

  /**
   * Convert lat/lon to MGRS string.
   * Implements UTM projection + MGRS grid letter lookup.
   * Valid for latitudes between 80°S and 84°N.
   */
  function latLonToMGRS(lat, lon) {
    if (lat < -80 || lat > 84) {
      return 'Outside MGRS coverage';
    }

    // UTM zone number
    var zoneNum = Math.floor((lon + 180) / 6) + 1;

    // Special zones for Norway/Svalbard
    if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) zoneNum = 32;
    if (lat >= 72 && lat < 84) {
      if (lon >= 0  && lon <  9) zoneNum = 31;
      else if (lon >= 9  && lon < 21) zoneNum = 33;
      else if (lon >= 21 && lon < 33) zoneNum = 35;
      else if (lon >= 33 && lon < 42) zoneNum = 37;
    }

    // UTM latitude band letter
    var bandLetters = 'CDEFGHJKLMNPQRSTUVWX';
    var bandIdx = Math.floor((lat + 80) / 8);
    if (bandIdx >= bandLetters.length) bandIdx = bandLetters.length - 1;
    var bandLetter = bandLetters[bandIdx];

    // UTM projection constants
    var a = 6378137;             // WGS84 semi-major axis
    var f = 1 / 298.257223563;   // WGS84 flattening
    var k0 = 0.9996;             // UTM scale factor
    var e = Math.sqrt(2 * f - f * f);
    var e2 = e * e;
    var ep2 = e2 / (1 - e2);

    var lonOrigin = (zoneNum - 1) * 6 - 180 + 3; // central meridian
    var lonRad = lon * Math.PI / 180;
    var latRad = lat * Math.PI / 180;
    var dLon = (lon - lonOrigin) * Math.PI / 180;

    var N = a / Math.sqrt(1 - e2 * Math.sin(latRad) * Math.sin(latRad));
    var T = Math.tan(latRad) * Math.tan(latRad);
    var C = ep2 * Math.cos(latRad) * Math.cos(latRad);
    var A2 = Math.cos(latRad) * dLon;

    // Meridional arc
    var M = a * (
      (1 - e2/4 - 3*e2*e2/64 - 5*e2*e2*e2/256) * latRad
      - (3*e2/8 + 3*e2*e2/32 + 45*e2*e2*e2/1024) * Math.sin(2*latRad)
      + (15*e2*e2/256 + 45*e2*e2*e2/1024) * Math.sin(4*latRad)
      - (35*e2*e2*e2/3072) * Math.sin(6*latRad)
    );

    var easting = k0 * N * (
      A2 + (1-T+C)*A2*A2*A2/6
      + (5-18*T+T*T+72*C-58*ep2)*A2*A2*A2*A2*A2/120
    ) + 500000;

    var northing = k0 * (
      M + N * Math.tan(latRad) * (
        A2*A2/2 + (5-T+9*C+4*C*C)*A2*A2*A2*A2/24
        + (61-58*T+T*T+600*C-330*ep2)*A2*A2*A2*A2*A2*A2/720
      )
    );

    if (lat < 0) northing += 10000000; // southern hemisphere offset

    // 100km grid square letters
    var setNum = ((zoneNum - 1) % 6);
    var e100k = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
    var eIdx = Math.floor(easting / 100000) - 1;
    // Column letters cycle through 8 per set, offset by set number
    var colOffset = setNum * 8;
    var e100kLetter = e100k[(colOffset + eIdx) % 24];

    // Row letters: cycle every 2,000,000m (20 letters), odd/even zones offset
    var n100k = 'ABCDEFGHJKLMNPQRSTUV';
    var rowOffset = (setNum % 2 === 0) ? 0 : 5;
    var nIdx = Math.floor(northing % 2000000 / 100000);
    var n100kLetter = n100k[(rowOffset + nIdx) % 20];

    // Format: "12S WC 12345 67890"
    var eStr = pad5(Math.floor(easting % 100000));
    var nStr = pad5(Math.floor(northing % 100000));

    return zoneNum + bandLetter + ' ' + e100kLetter + n100kLetter + ' ' + eStr + ' ' + nStr;
  }

  function pad5(n) {
    var s = '' + n;
    while (s.length < 5) s = '0' + s;
    return s;
  }

  // ── Unit conversion helpers ──────────────────────────────────────────

  var M_PER_FT = 0.3048;
  var M_PER_MI = 1609.344;
  var KPH_PER_MPS = 3.6;
  var MPH_PER_MPS = 2.23694;

  /** Format an altitude/elevation value in meters with appropriate units */
  function formatAltitude(meters) {
    if (useImperial) {
      var ft = meters / M_PER_FT;
      if (ft >= 5280 * 100) {        // >= 100 mi
        return (ft / 5280).toFixed(0) + ' mi';
      } else if (ft >= 5280) {       // >= 1 mi
        return (ft / 5280).toFixed(1) + ' mi';
      } else {
        return ft.toFixed(0) + ' ft';
      }
    } else {
      if (meters >= 1000000) {
        return (meters / 1000).toFixed(0) + ' km';
      } else if (meters >= 10000) {
        return (meters / 1000).toFixed(1) + ' km';
      } else if (meters >= 1000) {
        return (meters / 1000).toFixed(2) + ' km';
      } else {
        return meters.toFixed(0) + ' m';
      }
    }
  }

  /** Format a short distance (accuracy, small spans) in meters */
  function formatDistance(meters) {
    if (useImperial) {
      var ft = meters / M_PER_FT;
      return ft.toFixed(0) + ' ft';
    } else {
      return meters.toFixed(0) + ' m';
    }
  }

  /** Format a route-scale distance in meters */
  function formatRouteDistance(meters) {
    if (useImperial) {
      var mi = meters / M_PER_MI;
      return mi.toFixed(1) + ' mi';
    } else {
      if (meters >= 1000) {
        return (meters / 1000).toFixed(1) + ' km';
      }
      return meters.toFixed(0) + ' m';
    }
  }

  /** Format speed from m/s */
  function formatSpeed(mps) {
    if (useImperial) {
      return (mps * MPH_PER_MPS).toFixed(0) + ' mph';
    } else {
      return (mps * KPH_PER_MPS).toFixed(0) + ' km/h';
    }
  }

  // =====================================================================
  //  9. ADMIN TASK MONITOR
  // =====================================================================

  var adminTimer = null;
  var ADMIN_REFRESH_MS = 10000;

  // Known total tile counts for progress bars (from data pipeline config)
  var KNOWN_TOTALS = {
    'Elevation tiles': 1474959,
    'Imagery tiles': 1474959,
  };

  function initAdmin() {
    // Start polling when admin tab is visible
    var adminTab = document.querySelector('[data-panel="admin-panel"]');
    if (adminTab) {
      adminTab.addEventListener('click', function () {
        fetchAdminStatus();
        clearInterval(adminTimer);
        adminTimer = setInterval(fetchAdminStatus, ADMIN_REFRESH_MS);
      });
    }

    // Stop polling when switching away from admin tab
    var otherTabs = document.querySelectorAll('.tab-btn:not([data-panel="admin-panel"])');
    otherTabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        clearInterval(adminTimer);
        adminTimer = null;
      });
    });
  }

  function fetchAdminStatus() {
    fetch('/admin/status')
      .then(function (res) { return res.json(); })
      .then(function (data) {
        renderAdminServices(data.services || []);
        renderAdminDataTasks(data.data_tasks || []);
      })
      .catch(function (err) {
        var el = document.getElementById('admin-services');
        if (el) el.textContent = 'Failed to load status';
      });
  }

  function renderAdminServices(services) {
    var container = document.getElementById('admin-services');
    while (container.firstChild) container.removeChild(container.firstChild);

    services.forEach(function (svc) {
      var row = document.createElement('div');
      row.className = 'admin-service-row';

      var name = document.createElement('span');
      name.className = 'admin-service-name';
      name.textContent = svc.name;
      row.appendChild(name);

      var badge = document.createElement('span');
      var healthLabel = svc.health === 'healthy' ? 'healthy'
                      : svc.health === 'starting' ? 'starting'
                      : svc.status === 'running' ? 'running'
                      : 'exited';
      badge.className = 'admin-service-badge ' + healthLabel;
      badge.textContent = healthLabel;
      row.appendChild(badge);

      container.appendChild(row);

      // Show progress info if available
      if (svc.progress && svc.progress.phase) {
        var prog = document.createElement('div');
        prog.className = 'admin-service-progress';
        var text = svc.progress.phase;
        if (svc.progress.eta) text += ' — ETA: ' + svc.progress.eta;
        prog.textContent = text;
        container.appendChild(prog);
      }
    });
  }

  function renderAdminDataTasks(tasks) {
    var container = document.getElementById('admin-data-tasks');
    while (container.firstChild) container.removeChild(container.firstChild);

    if (tasks.length === 0) {
      container.textContent = 'No data files found';
      return;
    }

    tasks.forEach(function (task) {
      var row = document.createElement('div');
      row.className = 'admin-data-row';

      var header = document.createElement('div');
      header.className = 'admin-data-header';

      var name = document.createElement('span');
      name.className = 'admin-data-name';
      name.textContent = task.name;
      header.appendChild(name);

      var status = document.createElement('span');
      status.className = 'admin-data-status ' + task.status;
      status.textContent = task.status;
      header.appendChild(status);

      row.appendChild(header);

      // Detail line (tile count, feature count, or file size fallback)
      var count = task.tiles || task.features || 0;
      var detail = document.createElement('div');
      detail.className = 'admin-data-detail';

      if (count > 0) {
        var total = KNOWN_TOTALS[task.name];
        if (total && task.status === 'downloading') {
          var pct = (count / total * 100).toFixed(1);
          detail.textContent = count.toLocaleString() + ' / ' + total.toLocaleString() + ' tiles (' + pct + '%)';

          var bar = document.createElement('div');
          bar.className = 'admin-progress-bar';
          var fill = document.createElement('div');
          fill.className = 'admin-progress-fill';
          fill.style.width = pct + '%';
          bar.appendChild(fill);
          row.appendChild(detail);
          row.appendChild(bar);
        } else {
          detail.textContent = count.toLocaleString() + (task.tiles ? ' tiles' : ' features');
          row.appendChild(detail);
        }
      }

      container.appendChild(row);
    });
  }

  // =====================================================================
  //  10. POSITION DETAIL OVERLAY
  // =====================================================================

  function initPositionDetail() {
    var statusBar = document.getElementById('status-bar');
    var overlay   = document.getElementById('position-detail');
    var closeBtn  = document.getElementById('position-detail-close');

    // Tap status bar to open (works on all screen sizes)
    statusBar.style.pointerEvents = 'auto';
    statusBar.style.cursor = 'pointer';
    statusBar.addEventListener('click', function () {
      populatePositionDetail();
      overlay.classList.remove('hidden');
    });

    // Close button
    closeBtn.addEventListener('click', function () {
      overlay.classList.add('hidden');
    });

    // Tap backdrop to close
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) {
        overlay.classList.add('hidden');
      }
    });
  }

  function populatePositionDetail() {
    var body = document.getElementById('position-detail-body');
    while (body.firstChild) body.removeChild(body.firstChild);

    var center = map.getCenter();
    var gpsLat = gpsLastPos ? gpsLastPos[1] : null;
    var gpsLon = gpsLastPos ? gpsLastPos[0] : null;

    // GPS section
    body.appendChild(makeSectionTitle('GPS Receiver'));
    if (gpsLat !== null && !gpsStale) {
      body.appendChild(makeRow('Decimal', formatDD(gpsLat, 'NS') + '  ' + formatDD(gpsLon, 'EW')));
      body.appendChild(makeRow('DMS', formatDMS(gpsLat, 'NS') + '  ' + formatDMS(gpsLon, 'EW')));
      body.appendChild(makeRow('Maidenhead', latLonToMaidenhead(gpsLat, gpsLon, 8)));
      body.appendChild(makeRow('MGRS', latLonToMGRS(gpsLat, gpsLon)));

      // Show raw lat/lon for easy copy-paste into other apps
      body.appendChild(makeRow('Lat, Lon', gpsLat.toFixed(6) + ', ' + gpsLon.toFixed(6)));
    } else {
      body.appendChild(makeRow('Status', gpsStale ? 'Signal lost' : 'No fix'));
    }

    // Camera section
    body.appendChild(makeSectionTitle('Camera / Eye'));
    body.appendChild(makeRow('Decimal', formatDD(center.lat, 'NS') + '  ' + formatDD(center.lng, 'EW')));
    body.appendChild(makeRow('DMS', formatDMS(center.lat, 'NS') + '  ' + formatDMS(center.lng, 'EW')));
    body.appendChild(makeRow('Maidenhead', latLonToMaidenhead(center.lat, center.lng, 8)));
    body.appendChild(makeRow('MGRS', latLonToMGRS(center.lat, center.lng)));

    // Eye altitude
    var zoom = map.getZoom();
    var pitch = map.getPitch();
    var altMeters = 35200000 / Math.pow(2, zoom);
    if (pitch > 0) altMeters = altMeters / Math.cos(pitch * Math.PI / 180);
    body.appendChild(makeRow('Altitude', formatAltitude(altMeters)));
    body.appendChild(makeRow('Lat, Lon', center.lat.toFixed(6) + ', ' + center.lng.toFixed(6)));
  }

  function makeSectionTitle(text) {
    var el = document.createElement('div');
    el.className = 'position-section-title';
    el.textContent = text;
    return el;
  }

  function makeRow(label, value) {
    var row = document.createElement('div');
    row.className = 'position-row';

    var labelEl = document.createElement('span');
    labelEl.className = 'position-row-label';
    labelEl.textContent = label;

    var valueEl = document.createElement('span');
    valueEl.className = 'position-row-value';
    valueEl.textContent = value;

    row.appendChild(labelEl);
    row.appendChild(valueEl);

    // Tap to copy
    row.addEventListener('click', function () {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(value).then(function () {
          valueEl.classList.add('position-copied');
          var orig = valueEl.textContent;
          valueEl.textContent = 'Copied!';
          setTimeout(function () {
            valueEl.textContent = orig;
            valueEl.classList.remove('position-copied');
          }, 1200);
        });
      }
    });

    return row;
  }

  // =====================================================================
  //  10. FREE-LOOK CAMERA (Google Earth style)
  // =====================================================================
  //
  // Default MapLibre Ctrl+drag: orbits around a point ON THE GROUND.
  // Google Earth Ctrl: looks around from a fixed point IN THE SKY.
  //
  // We intercept Ctrl+mousedown to enter "free look" mode. While active,
  // mouse movement changes bearing and pitch while keeping the camera
  // position fixed (as if turning your head from a drone).
  //
  // Shift+drag retains MapLibre's default orbit behavior.

  function initFreeLookCamera() {
    var freeLookActive = false;
    var startX = 0;
    var startY = 0;
    var startBearing = 0;
    var startPitch = 0;

    var canvas = map.getCanvas();

    // Disable MapLibre's built-in Ctrl+drag rotation so we can override it
    map.dragRotate.disable();

    // Re-enable right-click drag for the default orbit (shift+drag style)
    map.on('mousedown', function (e) {
      if (e.originalEvent.button === 2) {
        // Right-click drag: use default orbit behavior
        map.dragRotate.enable();
      }
    });

    canvas.addEventListener('mousedown', function (e) {
      if (e.ctrlKey && e.button === 0) {
        // Ctrl+left click: enter free-look mode
        e.preventDefault();
        e.stopPropagation();
        freeLookActive = true;
        startX = e.clientX;
        startY = e.clientY;
        startBearing = map.getBearing();
        startPitch = map.getPitch();
        canvas.style.cursor = 'crosshair';

        // Prevent map from starting a regular drag
        map.dragPan.disable();
      }
    });

    window.addEventListener('mousemove', function (e) {
      if (!freeLookActive) return;
      e.preventDefault();

      var dx = e.clientX - startX;
      var dy = e.clientY - startY;

      // Horizontal movement = bearing change, vertical = pitch change
      // Sensitivity: 0.3 degrees per pixel
      var newBearing = startBearing + dx * 0.3;
      var newPitch = Math.max(0, Math.min(85, startPitch - dy * 0.3));

      map.jumpTo({
        bearing: newBearing,
        pitch: newPitch
      });
    });

    window.addEventListener('mouseup', function (e) {
      if (!freeLookActive) return;
      freeLookActive = false;
      canvas.style.cursor = '';
      map.dragPan.enable();
    });

    // Also support Shift+drag for ground-orbit (MapLibre default behavior)
    canvas.addEventListener('mousedown', function (e) {
      if (e.shiftKey && e.button === 0) {
        map.dragRotate.enable();
      }
    });
  }

  // =====================================================================
  //  BOOTSTRAP
  // =====================================================================

  document.addEventListener('DOMContentLoaded', function () {
    initMap();
    initSidebarTabs();
    initLayerControls();
    initSearch();
    initRouting();
    initImport();
    initGPS();
    initAdmin();
    // These need the map to be initialized first
    map.on('load', function () {
      initFreeLookCamera();
      initStatusBar();
      initPositionDetail();
    });
  });

})();
