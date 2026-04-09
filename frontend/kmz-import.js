/* =====================================================================
   Geographica — KMZ/KML Import Pipeline
   =====================================================================
   Extracted from app.js (Pitfall #9: keep modules under ~800 lines).
   Handles style resolution, icon loading, fallback generation, and
   chunked async processing for KMZ/KML imports.
   Exposes API via window._kmzImport for app.js to call.
   ===================================================================== */

(function () {
  'use strict';

  // =====================================================================
  //  CONSTANTS
  // =====================================================================

  var MAX_ICON_FETCHES = 50;
  var ICON_FETCH_TIMEOUT_MS = 5000;
  var ICON_PHASE_TIMEOUT_MS = 30000;
  var MAX_IMAGE_DIMENSION = 256;
  var MAX_KML_SIZE = 500 * 1024 * 1024;  // 500 MB decompression bomb limit
  var BATCH_SIZE = 500;

  // 8 hues for fallback icon colors (HSL at 60% saturation, 50% lightness)
  var FALLBACK_HUES = [0, 45, 90, 135, 180, 225, 270, 315];

  // =====================================================================
  //  ICON CACHE (session-scoped, survives style swaps)
  // =====================================================================

  var iconCache = new Map();       // url → { iconId, imageData: {width, height, data} }
  var iconRefCounts = {};          // iconId → number of files referencing it

  // =====================================================================
  //  STYLE RESOLUTION
  // =====================================================================

  /**
   * Walk KML DOM to build style and styleMap lookup tables.
   * @param {Document} kmlDoc - parsed KML DOM
   * @returns {{ styleTable: Object, styleMapTable: Object, urlToScale: Object }}
   */
  function buildStyleTables(kmlDoc) {
    var styleTable = {};      // styleId → { iconUrl, scale }
    var styleMapTable = {};   // styleMapId → { normal: styleId, highlight: styleId }
    var urlToScale = {};      // iconUrl → scale (reverse lookup)

    // Parse <Style> elements
    var styles = kmlDoc.getElementsByTagName('Style');
    for (var i = 0; i < styles.length; i++) {
      var styleEl = styles[i];
      var styleId = styleEl.getAttribute('id');
      if (!styleId) continue;

      var iconUrl = '';
      var scale = 1;

      var iconStyles = styleEl.getElementsByTagName('IconStyle');
      if (iconStyles.length > 0) {
        var icons = iconStyles[0].getElementsByTagName('Icon');
        if (icons.length > 0) {
          var hrefs = icons[0].getElementsByTagName('href');
          if (hrefs.length > 0 && hrefs[0].textContent) {
            iconUrl = hrefs[0].textContent.trim();
          }
        }
        var scales = iconStyles[0].getElementsByTagName('scale');
        if (scales.length > 0 && scales[0].textContent) {
          scale = parseFloat(scales[0].textContent) || 1;
        }
      }

      styleTable[styleId] = { iconUrl: iconUrl, scale: scale };
      if (iconUrl) {
        urlToScale[iconUrl] = scale;
      }
    }

    // Parse <StyleMap> elements
    var styleMaps = kmlDoc.getElementsByTagName('StyleMap');
    for (var j = 0; j < styleMaps.length; j++) {
      var smEl = styleMaps[j];
      var smId = smEl.getAttribute('id');
      if (!smId) continue;

      var entry = { normal: '', highlight: '' };
      var pairs = smEl.getElementsByTagName('Pair');
      for (var k = 0; k < pairs.length; k++) {
        var keyEl = pairs[k].getElementsByTagName('key');
        var urlEl = pairs[k].getElementsByTagName('styleUrl');
        if (keyEl.length > 0 && urlEl.length > 0) {
          var key = keyEl[0].textContent.trim();
          var ref = urlEl[0].textContent.trim().replace(/^#/, '');
          if (key === 'normal') entry.normal = ref;
          else if (key === 'highlight') entry.highlight = ref;
        }
      }
      styleMapTable[smId] = entry;
    }

    return { styleTable: styleTable, styleMapTable: styleMapTable, urlToScale: urlToScale };
  }

  /**
   * Resolve the icon URL and scale for a single GeoJSON feature.
   * @param {Object} props - feature.properties (from toGeoJSON)
   * @param {{ styleTable: Object, styleMapTable: Object, urlToScale: Object }} tables
   * @returns {{ iconUrl: string, scale: number }}
   */
  function resolveFeatureIcon(props, tables) {
    var iconUrl = '';
    var scale = 1;

    // Path 1: toGeoJSON resolved the icon URL directly
    if (props.icon && typeof props.icon === 'string') {
      iconUrl = props.icon;
      scale = tables.urlToScale[iconUrl] || 1;
      return { iconUrl: iconUrl, scale: scale };
    }

    // Path 2: styleUrl fallback — toGeoJSON preserved the reference
    if (props.styleUrl) {
      var ref = props.styleUrl.replace(/^#/, '');

      // Check styleMap first
      if (tables.styleMapTable[ref]) {
        var normalId = tables.styleMapTable[ref].normal;
        if (tables.styleTable[normalId]) {
          iconUrl = tables.styleTable[normalId].iconUrl;
          scale = tables.styleTable[normalId].scale;
        }
      }
      // Then direct style
      else if (tables.styleTable[ref]) {
        iconUrl = tables.styleTable[ref].iconUrl;
        scale = tables.styleTable[ref].scale;
      }
    }

    // Path 3: styleHash fallback (toGeoJSON generates these)
    if (!iconUrl && props.styleHash) {
      var hash = props.styleHash.replace(/^#/, '');
      if (tables.styleTable[hash]) {
        iconUrl = tables.styleTable[hash].iconUrl;
        scale = tables.styleTable[hash].scale;
      }
    }

    return { iconUrl: iconUrl || '', scale: scale };
  }

  // =====================================================================
  //  ICON ID + FALLBACK GENERATION
  // =====================================================================

  /**
   * Derive a deterministic icon ID from a URL.
   * @param {string} url
   * @returns {string} e.g. 'kmz-icon-adit-n-32'
   */
  function deriveIconId(url) {
    // Idempotent: return cached ID if this URL was already processed
    if (iconCache.has(url)) return iconCache.get(url).iconId;

    var filename = url.split('/').pop().split('?')[0] || 'unknown';
    var base = filename.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9]/g, '-');
    var candidate = 'kmz-icon-' + base;

    // Collision check against cache (different URL → same derived name)
    var suffix = 2;
    var original = candidate;
    iconCache.forEach(function (entry) {
      if (entry.iconId === candidate) {
        candidate = original + '-' + suffix;
        suffix++;
      }
    });

    return candidate;
  }

  /**
   * Derive a 2-letter abbreviation from a KML style name for fallback icons.
   * @param {string} styleName
   * @returns {string}
   */
  function deriveAbbreviation(styleName) {
    if (!styleName) return '??';
    var skipWords = { and: 1, or: 1, the: 1 };
    var parts = styleName.split(/[_\-\s]+/).filter(function (w) {
      return w.length > 0 && !skipWords[w.toLowerCase()];
    });
    var abbr = parts.map(function (w) { return w.charAt(0).toUpperCase(); }).join('');
    if (abbr.length === 0) return '??';
    if (abbr.length === 1) return abbr + abbr;
    return abbr.substring(0, 2);
  }

  /**
   * Simple string hash → index into FALLBACK_HUES.
   * @param {string} str
   * @returns {number} hue in degrees
   */
  function hashToHue(str) {
    var hash = 0;
    for (var i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash) + str.charCodeAt(i);
      hash = hash & hash;  // Convert to 32-bit int
    }
    return FALLBACK_HUES[Math.abs(hash) % FALLBACK_HUES.length];
  }

  /**
   * Generate a 32x32 fallback icon canvas image data.
   * @param {string} styleName - KML style name (for abbreviation + color hash)
   * @returns {{ width: number, height: number, data: Uint8Array }}
   */
  function generateFallbackIcon(styleName) {
    var abbr = deriveAbbreviation(styleName);
    var hue = hashToHue(styleName || 'default');

    var canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    var ctx = canvas.getContext('2d');

    // Filled circle
    ctx.beginPath();
    ctx.arc(16, 16, 14, 0, Math.PI * 2);
    ctx.fillStyle = 'hsl(' + hue + ', 60%, 50%)';
    ctx.fill();

    // White border
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Abbreviation text
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(abbr, 16, 17);

    var imageData = ctx.getImageData(0, 0, 32, 32);
    return {
      width: 32,
      height: 32,
      data: new Uint8Array(imageData.data.buffer)
    };
  }

  // =====================================================================
  //  ARCHIVE PATH VALIDATION
  // =====================================================================

  /**
   * Validate that an archive path is safe (no traversal attacks).
   * @param {string} path
   * @returns {boolean}
   */
  function isArchivePathSafe(path) {
    if (!path || typeof path !== 'string') return false;
    // Decode URL-encoded chars first
    var decoded;
    try {
      decoded = decodeURIComponent(path);
    } catch (_) {
      return false;
    }
    if (decoded.indexOf('\0') !== -1) return false;
    if (decoded.indexOf('..') !== -1) return false;
    if (decoded.charAt(0) === '/') return false;
    if (decoded.indexOf('\\') !== -1) return false;
    return true;
  }

  // =====================================================================
  //  ICON LOADING
  // =====================================================================

  /**
   * Load a single icon from archive or external URL, with fallback.
   * @param {string} url - icon URL from KML
   * @param {string} styleName - for fallback abbreviation
   * @param {Object|null} zipArchive - JSZip object (null for plain KML)
   * @param {Object} mapRef - MapLibre map instance
   * @returns {Promise<{ iconId: string, imageData: Object }>}
   */
  function loadSingleIcon(url, styleName, zipArchive, mapRef) {
    var iconId = deriveIconId(url);

    // Already cached?
    if (iconCache.has(url)) {
      var cached = iconCache.get(url);
      if (!mapRef.hasImage(cached.iconId)) {
        mapRef.addImage(cached.iconId, {
          width: cached.imageData.width,
          height: cached.imageData.height,
          data: new Uint8Array(cached.imageData.data.buffer)
        });
      }
      return Promise.resolve(cached);
    }

    // Already registered in map (from a previous import)?
    if (mapRef.hasImage(iconId)) {
      return Promise.resolve({ iconId: iconId, imageData: { alreadyLoaded: true } });
    }

    // Try archive path first
    if (zipArchive && isArchivePathSafe(url)) {
      var archiveFile = zipArchive.file(url);
      if (archiveFile) {
        return archiveFile.async('blob').then(function (blob) {
          return loadImageFromBlob(blob, iconId, url, styleName, mapRef);
        }).catch(function () {
          return registerFallback(iconId, url, styleName, mapRef);
        });
      }
    }

    // External URL — validate and fetch
    if (typeof isUrlSafe === 'function' && !isUrlSafe(url)) {
      return Promise.resolve(registerFallback(iconId, url, styleName, mapRef));
    }

    // Fetch with redirect blocking + timeout
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, ICON_FETCH_TIMEOUT_MS);

    return fetch(url, {
      redirect: 'error',
      signal: controller.signal
    }).then(function (response) {
      clearTimeout(timer);
      // Validate Content-Type
      var ct = response.headers.get('Content-Type') || '';
      if (ct.indexOf('image/') !== 0) {
        return registerFallback(iconId, url, styleName, mapRef);
      }
      // Post-fetch URL validation (DNS rebinding defense)
      if (typeof isUrlSafe === 'function' && !isUrlSafe(response.url)) {
        return registerFallback(iconId, url, styleName, mapRef);
      }
      return response.blob().then(function (blob) {
        return loadImageFromBlob(blob, iconId, url, styleName, mapRef);
      });
    }).catch(function () {
      clearTimeout(timer);
      return registerFallback(iconId, url, styleName, mapRef);
    });
  }

  /**
   * Load an image from a Blob, validate dimensions, register with map.
   * @returns {Promise<{ iconId: string, imageData: Object }>}
   */
  function loadImageFromBlob(blob, iconId, url, styleName, mapRef) {
    var blobUrl = URL.createObjectURL(blob);
    return new Promise(function (resolve) {
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(blobUrl);
        // Validate dimensions
        if (img.naturalWidth > MAX_IMAGE_DIMENSION || img.naturalHeight > MAX_IMAGE_DIMENSION) {
          resolve(registerFallback(iconId, url, styleName, mapRef));
          return;
        }
        var w = img.naturalWidth || 32;
        var h = img.naturalHeight || 32;
        var canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        var ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        var imageData = ctx.getImageData(0, 0, w, h);
        var entry = {
          iconId: iconId,
          imageData: { width: w, height: h, data: new Uint8Array(imageData.data.buffer) }
        };
        iconCache.set(url, entry);
        if (!mapRef.hasImage(iconId)) {
          mapRef.addImage(iconId, {
            width: entry.imageData.width,
            height: entry.imageData.height,
            data: new Uint8Array(entry.imageData.data.buffer)
          });
        }
        resolve(entry);
      };
      img.onerror = function () {
        URL.revokeObjectURL(blobUrl);
        resolve(registerFallback(iconId, url, styleName, mapRef));
      };
      img.src = blobUrl;
    });
  }

  /**
   * Register a fallback icon and cache it.
   */
  function registerFallback(iconId, url, styleName, mapRef) {
    var fallbackData = generateFallbackIcon(styleName || url);
    var entry = { iconId: iconId, imageData: fallbackData };
    iconCache.set(url, entry);
    if (!mapRef.hasImage(iconId)) {
      mapRef.addImage(iconId, {
        width: fallbackData.width,
        height: fallbackData.height,
        data: new Uint8Array(fallbackData.data.buffer)
      });
    }
    return entry;
  }

  /**
   * Load all unique icons from style tables.
   * @param {{ styleTable: Object, urlToScale: Object }} tables
   * @param {Object|null} zipArchive
   * @param {Object} mapRef
   * @param {function} onProgress - callback(loaded, total)
   * @returns {Promise<{ loaded: number, failed: number, total: number }>}
   */
  function loadAllIcons(tables, zipArchive, mapRef, onProgress) {
    // Collect unique icon URLs
    var urls = [];
    var urlSet = {};
    Object.keys(tables.styleTable).forEach(function (id) {
      var iconUrl = tables.styleTable[id].iconUrl;
      if (iconUrl && !urlSet[iconUrl]) {
        urlSet[iconUrl] = true;
        urls.push({ url: iconUrl, styleName: id });
      }
    });

    if (urls.length === 0) {
      return Promise.resolve({ loaded: 0, failed: 0, total: 0 });
    }

    // Cap at MAX_ICON_FETCHES
    var toLoad = urls.slice(0, MAX_ICON_FETCHES);
    var total = toLoad.length;

    // Offline short-circuit — use fallbacks for all icons
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      console.log('Offline mode — using fallback symbols for ' + total + ' icons.');
      toLoad.forEach(function (item) {
        var iconId = deriveIconId(item.url);
        registerFallback(iconId, item.url, item.styleName, mapRef);
      });
      if (onProgress) onProgress(total, total);
      return Promise.resolve({ loaded: 0, failed: total, total: total });
    }

    // Load in parallel with phase timeout
    var loaded = 0;
    var failed = 0;

    var promises = toLoad.map(function (item) {
      return loadSingleIcon(item.url, item.styleName, zipArchive, mapRef)
        .then(function (result) {
          if (result && result.imageData) {
            loaded++;
          } else {
            failed++;
          }
          if (onProgress) onProgress(loaded + failed, total);
          return result;
        });
    });

    // Phase timeout — resolve with whatever we have after 30s
    return new Promise(function (resolve) {
      var phaseTimer = setTimeout(function () {
        console.warn('Icon loading phase timeout (' + ICON_PHASE_TIMEOUT_MS + 'ms). Loaded ' + loaded + '/' + total);
        resolve({ loaded: loaded, failed: total - loaded, total: total });
      }, ICON_PHASE_TIMEOUT_MS);

      Promise.all(promises).then(function () {
        clearTimeout(phaseTimer);
        resolve({ loaded: loaded, failed: failed, total: total });
      });
    });
  }

  // =====================================================================
  //  PUBLIC API
  // =====================================================================

  window._kmzImport = {
    buildStyleTables: buildStyleTables,
    resolveFeatureIcon: resolveFeatureIcon,
    deriveIconId: deriveIconId,
    deriveAbbreviation: deriveAbbreviation,
    generateFallbackIcon: generateFallbackIcon,
    isArchivePathSafe: isArchivePathSafe,
    loadSingleIcon: loadSingleIcon,
    loadAllIcons: loadAllIcons,
    getIconCache: function () { return iconCache; },
    getIconRefCounts: function () { return iconRefCounts; },
    incrementIconRef: function (iconId) {
      iconRefCounts[iconId] = (iconRefCounts[iconId] || 0) + 1;
    },
    decrementIconRef: function (iconId, mapRef) {
      if (!iconRefCounts[iconId]) return;
      iconRefCounts[iconId]--;
      if (iconRefCounts[iconId] <= 0) {
        delete iconRefCounts[iconId];
        if (mapRef && mapRef.hasImage(iconId)) {
          mapRef.removeImage(iconId);
        }
        // Remove from cache
        iconCache.forEach(function (entry, url) {
          if (entry.iconId === iconId) {
            iconCache.delete(url);
          }
        });
      }
    },
    MAX_KML_SIZE: MAX_KML_SIZE,
    BATCH_SIZE: BATCH_SIZE
  };

})();
