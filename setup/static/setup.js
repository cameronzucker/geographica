/* Geographica Setup Wizard — JavaScript */
/* eslint-disable no-var */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  var currentStep = 1;
  var totalSteps = 5;
  var csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  var systemInfo = null;
  var presets = {};
  var map = null;
  var bboxRect = null;
  var ws = null;
  var healthTimer = null;
  var logVisible = false;

  // Accumulated config
  var config = {
    host_ip: '',
    tls_mode: 'http',
    data_path: '/srv/geographica/data',
    bbox: '',
    layers: {
      basemap: 'download',
      base_imagery: 'naip',
      detail_imagery: 'm2m',
      elevation: 'download'
    },
    base_imagery_zoom: 15
  };

  // Pipeline step labels
  var STEP_LABELS = {
    osm_download: 'Download OSM data',
    osm_merge: 'Merge OSM extracts',
    osm_copy: 'Copy OSM data',
    planetiler_pull: 'Pull Planetiler image',
    planetiler_build: 'Build basemap tiles',
    poi_build: 'Build POI index',
    osm_pois: 'Extract OSM POIs',
    public_lands: 'Process public lands',
    elevation: 'Download elevation data',
    base_imagery: 'Download base imagery',
    detail_imagery: 'Download detail imagery',
    fonts: 'Download fonts',
    docker_build: 'Build Docker images'
  };

  // ---------------------------------------------------------------------------
  // API helper
  // ---------------------------------------------------------------------------
  function api(method, path, body) {
    var opts = {
      method: method,
      headers: { 'Content-Type': 'application/json' }
    };
    if (method !== 'GET') {
      opts.headers['X-CSRF-Token'] = csrfToken;
    }
    if (body) {
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (text) {
          try {
            var err = JSON.parse(text);
            throw new Error(err.detail || 'Request failed (' + r.status + ')');
          } catch (e) {
            if (e.message && e.message.indexOf('Request failed') === 0) throw e;
            throw new Error('Request failed (' + r.status + '): ' + text.substring(0, 200));
          }
        });
      }
      return r.text().then(function (text) {
        if (!text) return {};
        try { return JSON.parse(text); }
        catch (e) { throw new Error('Invalid JSON response: ' + text.substring(0, 200)); }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // DOM helpers
  // ---------------------------------------------------------------------------
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function createEl(tag, className, textContent) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (textContent) el.textContent = textContent;
    return el;
  }

  // ---------------------------------------------------------------------------
  // Step navigation
  // ---------------------------------------------------------------------------
  function showStep(n) {
    if (n < 1 || n > totalSteps) return;
    currentStep = n;

    // Update tabs
    $$('.wizard-tab').forEach(function (tab) {
      var step = parseInt(tab.getAttribute('data-step'), 10);
      tab.classList.toggle('active', step === n);
      tab.classList.toggle('completed', step < n);
    });

    // Show/hide step panels
    $$('.step').forEach(function (el, i) {
      el.style.display = (i + 1 === n) ? '' : 'none';
    });

    // Navigation buttons
    var btnBack = $('#btn-back');
    var btnNext = $('#btn-next');
    btnBack.style.display = (n > 1) ? '' : 'none';

    if (n === 4) {
      btnNext.textContent = preflightPassed ? 'Start Pipeline' : 'Run Checks';
      btnNext.style.display = '';
    } else if (n === 5) {
      btnNext.style.display = 'none';
    } else if (n === 2) {
      // Button text hints at skip-all behavior
      btnNext.textContent = isAllSkipped() ? 'Skip to Launch' : 'Next';
      btnNext.style.display = '';
    } else {
      btnNext.textContent = 'Next';
      btnNext.style.display = '';
    }

    // Step-specific init
    if (n === 1) loadSystemInfo();
    if (n === 2) initRegionStep();
    if (n === 3) loadCredentials();
    if (n === 4) {
      if (!preflightPassed) {
        $('#preflight-section').style.display = '';
        $('#pipeline-section').style.display = 'none';
        runPreflightChecks();
      } else {
        $('#preflight-section').style.display = 'none';
        $('#pipeline-section').style.display = '';
      }
    }
    if (n === 5) startHealthPolling();
  }

  function nextStep() {
    if (currentStep === 1) {
      config.host_ip = $('#host-ip').value.trim();
      config.tls_mode = $('#tls-mode').value;
      config.data_path = $('#data-path').value;
      if (!config.host_ip) {
        $('#host-ip-hint').textContent = 'Required';
        $('#host-ip-hint').className = 'field-hint error';
        return;
      }
    }

    if (currentStep === 2) {
      var allSkipped = isAllSkipped();
      config.bbox = $('#bbox-input').value.trim();
      if (!allSkipped) {
        if (!config.bbox) {
          $('#bbox-hint').textContent = 'Required (or skip all data layers)';
          $('#bbox-hint').className = 'field-hint error';
          return;
        }
        var parts = config.bbox.split(',');
        if (parts.length !== 4 || parts.some(function (p) { return isNaN(parseFloat(p)); })) {
          $('#bbox-hint').textContent = 'Must be west,south,east,north';
          $('#bbox-hint').className = 'field-hint error';
          return;
        }
      }
      config.base_imagery_zoom = parseInt($('#base-imagery-zoom').value, 10);

      // All skipped: save config now and jump straight to Launch
      if (allSkipped) {
        saveConfig();
        showStep(5);
        return;
      }
    }

    if (currentStep === 3) {
      saveConfig();
      saveCredentials();
    }

    if (currentStep === 4) {
      startPipeline();
      return;
    }

    showStep(currentStep + 1);
  }

  function isAllSkipped() {
    return config.layers.basemap === 'skip' &&
           config.layers.base_imagery === 'skip' &&
           config.layers.detail_imagery === 'skip' &&
           config.layers.elevation === 'skip';
  }

  function prevStep() {
    if (currentStep <= 1) return;
    // If on Launch (5) and all data was skipped, go back to Region (2) not Download (4)
    if (currentStep === 5 && isAllSkipped()) {
      showStep(2);
      return;
    }
    showStep(currentStep - 1);
  }

  // ---------------------------------------------------------------------------
  // Step 1: System info
  // ---------------------------------------------------------------------------
  function loadSystemInfo() {
    api('GET', '/api/system').then(function (data) {
      systemInfo = data;
      $('#host-ip').value = data.host_ip || '';
      config.host_ip = data.host_ip || '';
      $('#host-ip-hint').textContent = data.host_ip ? 'Auto-detected' : 'Could not detect';

      var ramMb = data.ram_mb || 0;
      var ramGb = (ramMb / 1024).toFixed(1);
      $('#ram-amount').textContent = ramGb + ' GB';
      var profileLabel = ramMb >= 12000 ? '16 GB profile' : '8 GB profile';
      $('#ram-profile-hint').textContent = profileLabel;

      // Storage options
      var sel = $('#data-path');
      sel.textContent = '';
      if (data.storage && data.storage.length > 0) {
        data.storage.forEach(function (s) {
          var opt = document.createElement('option');
          var path = s.path === '/' ? '/srv/geographica/data' : s.path + '/geographica/data';
          opt.value = path;
          opt.textContent = s.device + ' - ' + s.path + ' (' + s.free_gb + ' GB free of ' + s.total_gb + ' GB)';
          sel.appendChild(opt);
        });
      }
      // Always include default
      var hasDefault = false;
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === '/srv/geographica/data') { hasDefault = true; break; }
      }
      if (!hasDefault) {
        var dopt = document.createElement('option');
        dopt.value = '/srv/geographica/data';
        dopt.textContent = '/srv/geographica/data (default)';
        sel.insertBefore(dopt, sel.firstChild);
      }
      sel.value = config.data_path;

      if (data.existing_env) {
        $('#host-ip-hint').textContent = 'Existing .env found - values pre-filled';
      }
    }).catch(function (err) {
      $('#host-ip-hint').textContent = 'Detection failed: ' + err.message;
      $('#host-ip-hint').className = 'field-hint error';
    });
  }

  // TLS mode change handler
  function onTlsModeChange() {
    var mode = $('#tls-mode').value;
    var certGroup = $('#tls-cert-group');
    var hint = $('#tls-hint');

    if (mode === 'existing') {
      certGroup.style.display = '';
      hint.textContent = 'Scanning for certificates...';
      api('POST', '/api/tls/scan').then(function (data) {
        var list = $('#tls-cert-list');
        list.textContent = '';
        if (data.certs && data.certs.length > 0) {
          data.certs.forEach(function (c) {
            var div = createEl('div', 'cert-item', c.subject + ' (expires: ' + c.expires + ')');
            list.appendChild(div);
          });
          hint.textContent = data.certs.length + ' certificate(s) found';
        } else {
          list.appendChild(createEl('span', 'field-hint', 'No certificates found'));
          hint.textContent = 'No certificates found';
        }
      });
    } else {
      certGroup.style.display = 'none';
      if (mode === 'self-signed') {
        hint.textContent = 'A self-signed certificate will be generated';
      } else if (mode === 'external') {
        hint.textContent = 'TLS handled by external proxy (e.g. Tailscale)';
      } else {
        hint.textContent = '';
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Step 2: Region & Map
  // ---------------------------------------------------------------------------
  function initRegionStep() {
    loadPresets();
    if (!map) {
      initRegionMap();
    }
    updateSkipAllWarning();
  }

  function loadPresets() {
    api('GET', '/api/presets').then(function (data) {
      presets = data;
      var sel = $('#preset-select');
      sel.textContent = '';
      var defaultOpt = document.createElement('option');
      defaultOpt.value = '';
      defaultOpt.textContent = '-- Select a preset --';
      sel.appendChild(defaultOpt);
      Object.keys(data).forEach(function (key) {
        var opt = document.createElement('option');
        opt.value = key;
        opt.textContent = data[key].label;
        sel.appendChild(opt);
      });
    });
  }

  function initRegionMap() {
    map = new maplibregl.Map({
      container: 'region-map',
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '&copy; OpenStreetMap contributors',
            maxzoom: 18
          }
        },
        layers: [{
          id: 'osm-tiles',
          type: 'raster',
          source: 'osm',
          minzoom: 0,
          maxzoom: 18
        }]
      },
      center: [-111, 40],
      zoom: 3,
      attributionControl: false
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

    map.on('load', function () {
      // Add bbox rectangle source/layer
      map.addSource('bbox-rect', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[]] } }
      });
      map.addLayer({
        id: 'bbox-fill',
        type: 'fill',
        source: 'bbox-rect',
        paint: {
          'fill-color': '#3fb950',
          'fill-opacity': 0.15
        }
      });
      map.addLayer({
        id: 'bbox-outline',
        type: 'line',
        source: 'bbox-rect',
        paint: {
          'line-color': '#3fb950',
          'line-width': 2,
          'line-dasharray': [3, 2]
        }
      });

      // If bbox already set, draw it
      if (config.bbox) {
        updateMapBbox(config.bbox);
      }
    });

    // Shift+click-drag to draw bbox
    var drawing = false;
    var startLngLat = null;

    map.on('mousedown', function (e) {
      if (e.originalEvent.shiftKey) {
        drawing = true;
        startLngLat = e.lngLat;
        map.dragPan.disable();
        e.preventDefault();
      }
    });

    map.on('mousemove', function (e) {
      if (!drawing || !startLngLat) return;
      var west = Math.min(startLngLat.lng, e.lngLat.lng);
      var east = Math.max(startLngLat.lng, e.lngLat.lng);
      var south = Math.min(startLngLat.lat, e.lngLat.lat);
      var north = Math.max(startLngLat.lat, e.lngLat.lat);
      var bbox = west.toFixed(1) + ',' + south.toFixed(1) + ',' + east.toFixed(1) + ',' + north.toFixed(1);
      drawBboxOnMap(west, south, east, north);
      $('#bbox-input').value = bbox;
    });

    map.on('mouseup', function () {
      if (drawing) {
        drawing = false;
        startLngLat = null;
        map.dragPan.enable();
        config.bbox = $('#bbox-input').value;
        validateBbox();
      }
    });
  }

  function updateMapBbox(bboxStr) {
    var parts = bboxStr.split(',').map(parseFloat);
    if (parts.length !== 4 || parts.some(isNaN)) return;
    var west = parts[0], south = parts[1], east = parts[2], north = parts[3];
    drawBboxOnMap(west, south, east, north);

    // Fit map to bbox
    map.fitBounds([[west, south], [east, north]], { padding: 40 });
  }

  function drawBboxOnMap(west, south, east, north) {
    if (!map || !map.getSource('bbox-rect')) return;
    map.getSource('bbox-rect').setData({
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [west, south],
          [east, south],
          [east, north],
          [west, north],
          [west, south]
        ]]
      }
    });
  }

  function validateBbox() {
    var val = $('#bbox-input').value.trim();
    if (!val) {
      $('#bbox-hint').textContent = '';
      return;
    }
    api('POST', '/api/validate-bbox', { bbox: val }).then(function (data) {
      if (data.valid) {
        $('#bbox-hint').textContent = 'Valid';
        $('#bbox-hint').className = 'field-hint ok';
      } else {
        $('#bbox-hint').textContent = 'Invalid bounding box';
        $('#bbox-hint').className = 'field-hint error';
      }
    });
  }

  function updateSkipAllWarning() {
    var skipped = isAllSkipped();
    $('#skip-all-box').style.display = skipped ? '' : 'none';
    // Update Next button text dynamically on Step 2
    if (currentStep === 2) {
      $('#btn-next').textContent = skipped ? 'Skip to Launch' : 'Next';
    }
  }

  // ---------------------------------------------------------------------------
  // Step 3: Credentials
  // ---------------------------------------------------------------------------
  function loadCredentials() {
    var needsM2m = config.layers.detail_imagery === 'm2m';
    var needsCop = config.layers.detail_imagery === 'copernicus' ||
                   config.layers.base_imagery === 'sentinel';
    var needsNone = !needsM2m && !needsCop;

    $('#cred-m2m-group').style.display = needsM2m ? '' : 'none';
    $('#cred-copernicus-group').style.display = needsCop ? '' : 'none';
    $('#cred-none-msg').style.display = needsNone ? '' : 'none';
  }

  function saveConfig() {
    api('POST', '/api/config', {
      host_ip: config.host_ip,
      tls_mode: config.tls_mode,
      bbox: config.bbox,
      data_path: config.data_path
    }).catch(function (err) {
      console.error('Failed to save config:', err);
    });
  }

  function saveCredentials() {
    var m2mUser = $('#m2m-username').value.trim();
    var m2mToken = $('#m2m-token').value.trim();
    var copId = $('#copernicus-client-id').value.trim();
    var copSecret = $('#copernicus-client-secret').value.trim();

    // Only save if something was filled in
    if (!m2mUser && !m2mToken && !copId && !copSecret) return;

    api('POST', '/api/credentials', {
      m2m_username: m2mUser,
      m2m_token: m2mToken,
      copernicus_client_id: copId,
      copernicus_client_secret: copSecret
    }).catch(function (err) {
      console.error('Failed to save credentials:', err);
    });
  }

  // ---------------------------------------------------------------------------
  // Step 4: Preflight checks
  // ---------------------------------------------------------------------------
  var preflightPassed = false;
  var failedStep = null;

  function runPreflightChecks() {
    var list = $('#preflight-list');
    list.textContent = '';
    preflightPassed = false;

    // Show loading state
    var loadingItem = createEl('div', 'preflight-item');
    var loadingDot = createEl('div', 'preflight-dot checking');
    loadingItem.appendChild(loadingDot);
    loadingItem.appendChild(createEl('span', 'preflight-name', 'Checking dependencies...'));
    list.appendChild(loadingItem);

    api('GET', '/api/preflight').then(function (data) {
      list.textContent = '';
      var allOk = true;

      data.checks.forEach(function (check) {
        var item = createEl('div', 'preflight-item');
        var dot = createEl('div', 'preflight-dot ' + check.status);
        item.appendChild(dot);
        item.appendChild(createEl('span', 'preflight-name', check.label || check.name));

        if (check.status === 'ok') {
          item.appendChild(createEl('span', 'preflight-version', check.version || ''));
        } else {
          allOk = false;
          item.appendChild(createEl('span', 'preflight-version', check.message || 'Not available'));
          // Add fix button if dependency is fixable
          var actionDiv = createEl('div', 'preflight-action');
          var fixBtn = document.createElement('button');
          fixBtn.className = 'btn-fix';
          fixBtn.textContent = 'Install';
          fixBtn.setAttribute('data-dep', check.name);
          fixBtn.addEventListener('click', function () {
            fixDependency(check.name, fixBtn);
          });
          actionDiv.appendChild(fixBtn);
          item.appendChild(actionDiv);
        }
        list.appendChild(item);
      });

      var actionsEl = $('#preflight-actions');
      actionsEl.style.display = '';

      if (allOk) {
        preflightPassed = true;
        $('#preflight-section').style.display = 'none';
        $('#pipeline-section').style.display = '';
      }
    }).catch(function (err) {
      list.textContent = '';
      var errItem = createEl('div', 'preflight-item');
      var errDot = createEl('div', 'preflight-dot error');
      errItem.appendChild(errDot);
      errItem.appendChild(createEl('span', 'preflight-name', 'Preflight check failed: ' + err.message));
      list.appendChild(errItem);
      $('#preflight-actions').style.display = '';
    });
  }

  function fixDependency(depName, btn) {
    btn.disabled = true;
    btn.textContent = 'Installing...';

    api('POST', '/api/fix-dependency', { dependency: depName }).then(function (data) {
      if (data.ok) {
        btn.textContent = 'Installed';
        // Re-run preflight after a short delay
        setTimeout(runPreflightChecks, 500);
      } else {
        btn.textContent = 'Failed';
        btn.disabled = false;
      }
    }).catch(function () {
      btn.textContent = 'Failed';
      btn.disabled = false;
    });
  }

  // ---------------------------------------------------------------------------
  // Step 4: Pipeline
  // ---------------------------------------------------------------------------
  function startPipeline() {
    // Run preflight first if not already passed
    if (!preflightPassed) {
      runPreflightChecks();
      return;
    }

    // Build layer list from config
    var layers = [];
    Object.keys(config.layers).forEach(function (key) {
      if (config.layers[key] !== 'skip') {
        layers.push(key);
      }
    });

    // Render substep list
    renderSubsteps();

    // Disable next button during pipeline
    $('#btn-next').disabled = true;
    $('#btn-next').textContent = 'Running...';

    // Hide error actions from any previous run
    $('#error-actions').style.display = 'none';
    failedStep = null;

    api('POST', '/api/start', {
      bbox: config.bbox,
      layers: layers,
      data_path: config.data_path
    }).then(function () {
      connectProgress();
    }).catch(function (err) {
      showPipelineError('Pipeline start', err.message);
      $('#btn-next').disabled = false;
      $('#btn-next').textContent = 'Retry';
    });
  }

  function showPipelineError(stepName, message) {
    var errorActions = $('#error-actions');
    errorActions.style.display = '';
    $('#error-step-name').textContent = 'Failed: ' + stepName;
    failedStep = stepName;
    appendLog('[ERROR] ' + stepName + ': ' + message + '\n');
  }

  function renderSubsteps() {
    var list = $('#substep-list');
    list.textContent = '';
    var steps = Object.keys(STEP_LABELS);
    steps.forEach(function (key) {
      var item = createEl('div', 'substep-item');
      item.id = 'substep-' + key;
      item.appendChild(createEl('div', 'substep-dot'));
      item.appendChild(createEl('span', null, STEP_LABELS[key]));
      list.appendChild(item);
    });
  }

  function connectProgress() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + location.host + '/ws/progress';
    ws = new WebSocket(url);

    ws.onmessage = function (e) {
      var event;
      try {
        event = JSON.parse(e.data);
      } catch (err) {
        return;
      }
      handleProgressEvent(event);
    };

    ws.onclose = function () {
      // Reconnect after 2 seconds
      setTimeout(connectProgress, 2000);
    };

    ws.onerror = function () {
      // Will trigger onclose
    };
  }

  function handleProgressEvent(event) {
    var type = event.type;
    var el;

    if (type === 'step_start') {
      el = $('#substep-' + event.step);
      if (el) {
        el.className = 'substep-item active';
      }
      if (typeof event.progress_pct === 'number') {
        updateProgressBar(event.progress_pct);
      }
    }

    if (type === 'step_done') {
      el = $('#substep-' + event.step);
      if (el) {
        el.className = 'substep-item done';
      }
    }

    if (type === 'skip') {
      el = $('#substep-' + event.step);
      if (el) {
        el.className = 'substep-item skip done';
      }
    }

    if (type === 'output') {
      appendLog(event.text);
    }

    if (type === 'warning') {
      appendLog('[WARNING] ' + event.message);
    }

    if (type === 'error') {
      if (event.step) {
        el = $('#substep-' + event.step);
        if (el) {
          el.className = 'substep-item error';
        }
        showPipelineError(STEP_LABELS[event.step] || event.step, event.message || 'Unknown error');
      } else {
        appendLog('[ERROR] ' + (event.message || 'Unknown error') + '\n');
      }
      $('#btn-next').disabled = false;
      $('#btn-next').textContent = 'Retry';
    }

    if (type === 'pipeline_done') {
      updateProgressBar(100);
      $('#btn-next').disabled = false;
      $('#btn-next').textContent = 'Next';
      // Auto-advance to step 5
      showStep(5);
    }

    // Update overall progress from state events
    if (typeof event.progress_pct === 'number') {
      updateProgressBar(event.progress_pct);
    }
    if (event.running === false && event.step === 'done') {
      updateProgressBar(100);
    }
  }

  function updateProgressBar(pct) {
    $('#pipeline-progress').style.width = pct + '%';
    $('#pipeline-pct').textContent = pct + '%';
  }

  function appendLog(text) {
    var pre = $('#log-output');
    pre.textContent += text;
    // Auto-scroll
    var viewer = $('#log-viewer');
    viewer.scrollTop = viewer.scrollHeight;
  }

  function toggleLog() {
    logVisible = !logVisible;
    $('#log-viewer').style.display = logVisible ? '' : 'none';
    $('#btn-toggle-log').textContent = logVisible ? 'Hide log' : 'Show log';
  }

  // ---------------------------------------------------------------------------
  // Step 5: Health
  // ---------------------------------------------------------------------------
  function startHealthPolling() {
    // First, launch (or detect existing stack)
    var statusEl = $('#launch-status');
    if (statusEl) statusEl.textContent = 'Checking stack status...';

    api('POST', '/api/launch').then(function (data) {
      if (statusEl) {
        if (data.state === 'already_healthy') {
          statusEl.textContent = 'Existing stack detected — all ' + data.existing_count + ' services already running and healthy.';
          statusEl.className = 'launch-status detected';
        } else if (data.state === 'restarted') {
          statusEl.textContent = 'Existing stack detected (' + data.existing_count + ' services). Restarted — waiting for health checks...';
          statusEl.className = 'launch-status restarted';
        } else {
          statusEl.textContent = 'Stack launched — waiting for health checks...';
          statusEl.className = 'launch-status started';
        }
      }
      // Hide the manual launch button since we auto-launched
      if ($('#launch-actions')) $('#launch-actions').style.display = 'none';
    }).catch(function (err) {
      if (statusEl) {
        statusEl.textContent = 'Failed to launch stack: ' + err.message;
        statusEl.className = 'launch-status error';
      }
    });

    pollHealth();
    if (healthTimer) clearInterval(healthTimer);
    healthTimer = setInterval(pollHealth, 5000);
  }

  function pollHealth() {
    api('GET', '/api/health').then(function (data) {
      renderHealth(data.services || []);
    }).catch(function () {
      renderHealth([]);
    });
  }

  function renderHealth(services) {
    var container = $('#service-health');
    container.textContent = '';

    if (services.length === 0) {
      var row = createEl('div', 'service-row');
      row.appendChild(createEl('span', 'service-dot unknown'));
      row.appendChild(createEl('span', 'service-name', 'No services detected'));
      row.appendChild(createEl('span', 'service-status', 'Stack may not be running'));
      container.appendChild(row);
      return;
    }

    var allHealthy = true;
    services.forEach(function (svc) {
      var name = svc.Name || svc.Service || 'unknown';
      var state = svc.State || 'unknown';
      var health = svc.Health || '';
      var statusClass = 'unknown';
      var statusText = state;

      if (state === 'running') {
        if (health === 'healthy') {
          statusClass = 'healthy';
          statusText = 'Healthy';
        } else if (health === 'unhealthy') {
          statusClass = 'unhealthy';
          statusText = 'Unhealthy';
          allHealthy = false;
        } else {
          statusClass = 'starting';
          statusText = 'Starting';
          allHealthy = false;
        }
      } else {
        statusClass = 'unhealthy';
        allHealthy = false;
      }

      var row = createEl('div', 'service-row');
      row.appendChild(createEl('span', 'service-dot ' + statusClass));
      row.appendChild(createEl('span', 'service-name', name));
      row.appendChild(createEl('span', 'service-status', statusText));
      container.appendChild(row);
    });

    if (allHealthy && services.length > 0) {
      $('#completion-msg').style.display = '';
      $('#launch-actions').style.display = 'none';
      // Build app link
      var proto = config.tls_mode === 'http' ? 'http' : 'https';
      var host = config.host_ip || location.hostname;
      var port = (config.tls_mode === 'http') ? ':8093' : '';  // HTTPS on 443 (default), HTTP on 8093
      $('#app-link').href = proto + '://' + host + port;
    }
  }

  function launchStack() {
    $('#btn-launch').disabled = true;
    $('#btn-launch').textContent = 'Launching...';

    api('POST', '/api/launch').then(function (data) {
      if (data.exit_code === 0) {
        $('#btn-launch').textContent = 'Launched - waiting for health...';
      } else {
        $('#btn-launch').textContent = 'Launch failed';
        $('#btn-launch').disabled = false;
        alert('Launch failed:\n' + (data.output || 'Unknown error'));
      }
    }).catch(function (err) {
      $('#btn-launch').textContent = 'Launch failed';
      $('#btn-launch').disabled = false;
      alert('Launch error: ' + err.message);
    });
  }

  // ---------------------------------------------------------------------------
  // Source button handlers
  // ---------------------------------------------------------------------------
  function initSourceButtons() {
    $$('.source-btns').forEach(function (group) {
      var buttons = group.querySelectorAll('.source-btn');
      buttons.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var layer = btn.getAttribute('data-layer');
          var value = btn.getAttribute('data-value');
          if (!layer) return;

          // Deactivate siblings in this layer
          buttons.forEach(function (b) {
            if (b.getAttribute('data-layer') === layer) {
              b.classList.remove('active');
            }
          });
          btn.classList.add('active');
          config.layers[layer] = value;

          // Update credential warning visibility
          if (layer === 'detail_imagery') {
            var warn = $('#detail-cred-warning');
            warn.style.display = (value === 'skip') ? 'none' : '';
          }

          updateSkipAllWarning();
        });
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Zoom slider
  // ---------------------------------------------------------------------------
  function initZoomSlider() {
    var slider = $('#base-imagery-zoom');
    var label = $('#base-imagery-zoom-val');
    if (!slider) return;
    slider.addEventListener('input', function () {
      label.textContent = 'z' + slider.value;
      config.base_imagery_zoom = parseInt(slider.value, 10);
    });
  }

  // ---------------------------------------------------------------------------
  // Preset change handler
  // ---------------------------------------------------------------------------
  function onPresetChange() {
    var key = $('#preset-select').value;
    if (!key || !presets[key]) return;
    var preset = presets[key];
    $('#bbox-input').value = preset.bbox;
    config.bbox = preset.bbox;
    if (map && map.getSource('bbox-rect')) {
      updateMapBbox(preset.bbox);
    }
    validateBbox();
  }

  // ---------------------------------------------------------------------------
  // Bbox input handler
  // ---------------------------------------------------------------------------
  function onBboxInput() {
    var val = $('#bbox-input').value.trim();
    config.bbox = val;
    if (map && map.getSource('bbox-rect') && val) {
      updateMapBbox(val);
    }
    // Debounced validation
    clearTimeout(onBboxInput._timer);
    onBboxInput._timer = setTimeout(validateBbox, 400);
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------
  function init() {
    // Button handlers
    $('#btn-next').addEventListener('click', nextStep);
    $('#btn-back').addEventListener('click', prevStep);
    $('#btn-toggle-log').addEventListener('click', toggleLog);
    $('#btn-launch').addEventListener('click', launchStack);
    $('#btn-skip-creds').addEventListener('click', function () {
      showStep(currentStep + 1);
    });

    // Preflight recheck
    $('#btn-recheck').addEventListener('click', runPreflightChecks);

    // Pipeline error retry/skip
    $('#btn-retry-step').addEventListener('click', function () {
      $('#error-actions').style.display = 'none';
      startPipeline();
    });
    $('#btn-skip-step').addEventListener('click', function () {
      $('#error-actions').style.display = 'none';
      appendLog('[SKIP] Skipped failed step\n');
      // Re-enable next button
      $('#btn-next').disabled = false;
      $('#btn-next').textContent = 'Next';
    });

    // TLS mode change
    $('#tls-mode').addEventListener('change', onTlsModeChange);

    // Preset change
    $('#preset-select').addEventListener('change', onPresetChange);

    // Bbox input
    $('#bbox-input').addEventListener('input', onBboxInput);

    // Source button handlers
    initSourceButtons();

    // Zoom slider
    initZoomSlider();

    // Tab click handlers (only allow going back, not forward)
    $$('.wizard-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        var step = parseInt(tab.getAttribute('data-step'), 10);
        if (step < currentStep) {
          showStep(step);
        }
      });
    });

    // Start at step 1
    showStep(1);
  }

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
