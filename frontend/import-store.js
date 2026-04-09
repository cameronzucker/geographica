/* =====================================================================
   Geographica — Import Session Persistence
   =====================================================================
   Wraps IndexedDB for session-scoped persistence of KMZ/KML imports.
   Exposes API via window._importStore for app.js to call.
   ===================================================================== */

(function () {
  'use strict';

  var DB_NAME = 'geographica-imports';
  var DB_VERSION = 1;
  var STORE_NAME = 'imports';
  var SESSION_KEY = 'geographica-session-id';
  var MAX_FILES = 5;
  var STALE_TTL_MS = 60 * 60 * 1000;
  var HARD_TTL_MS = 24 * 60 * 60 * 1000;

  var db = null;
  var sessionId = '';

  function getOrCreateSessionId() {
    var existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    var hex = '';
    for (var i = 0; i < bytes.length; i++) {
      hex += ('0' + bytes[i].toString(16)).slice(-2);
    }
    sessionStorage.setItem(SESSION_KEY, hex);
    return hex;
  }

  function openDB() {
    return new Promise(function (resolve, reject) {
      if (typeof indexedDB === 'undefined') {
        reject(new Error('IndexedDB not available'));
        return;
      }
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        var database = e.target.result;
        if (!database.objectStoreNames.contains(STORE_NAME)) {
          database.createObjectStore(STORE_NAME, { keyPath: 'fileId' });
        }
      };
      req.onsuccess = function (e) { resolve(e.target.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function purgeStale(database, currentSessionId) {
    return new Promise(function (resolve) {
      var tx = database.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        var entries = req.result || [];
        var now = Date.now();
        entries.forEach(function (entry) {
          var age = now - (entry.savedAt || 0);
          if (age > HARD_TTL_MS) {
            store.delete(entry.fileId);
          } else if (entry.sessionId !== currentSessionId && age > STALE_TTL_MS) {
            store.delete(entry.fileId);
          }
        });
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { resolve(); };
      };
      req.onerror = function () { resolve(); };
    });
  }

  function readSessionEntries(database, currentSessionId) {
    return new Promise(function (resolve) {
      var tx = database.transaction(STORE_NAME, 'readonly');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        var entries = (req.result || []).filter(function (e) {
          return e.sessionId === currentSessionId;
        });
        entries.sort(function (a, b) { return (b.savedAt || 0) - (a.savedAt || 0); });
        if (entries.length > MAX_FILES) {
          var excess = entries.splice(MAX_FILES);
          try {
            var dtx = database.transaction(STORE_NAME, 'readwrite');
            var dstore = dtx.objectStore(STORE_NAME);
            excess.forEach(function (e) { dstore.delete(e.fileId); });
          } catch (_) { /* best effort */ }
        }
        resolve(entries);
      };
      req.onerror = function () { resolve([]); };
    });
  }

  function countSessionEntries(database, currentSessionId) {
    return new Promise(function (resolve) {
      var tx = database.transaction(STORE_NAME, 'readonly');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        var count = (req.result || []).filter(function (e) {
          return e.sessionId === currentSessionId;
        }).length;
        resolve(count);
      };
      req.onerror = function () { resolve(0); };
    });
  }

  function init(callback) {
    sessionId = getOrCreateSessionId();
    openDB().then(function (database) {
      db = database;
      return purgeStale(db, sessionId).then(function () {
        return readSessionEntries(db, sessionId);
      });
    }).then(function (entries) {
      callback(entries);
    }).catch(function (err) {
      console.warn('IndexedDB unavailable — import persistence disabled:', err.message);
      db = null;
      callback([]);
    });

    window.addEventListener('pagehide', function (e) {
      if (e.persisted === false && db) {
        try {
          var tx = db.transaction(STORE_NAME, 'readwrite');
          var store = tx.objectStore(STORE_NAME);
          var req = store.getAll();
          req.onsuccess = function () {
            (req.result || []).forEach(function (entry) {
              if (entry.sessionId === sessionId) {
                store.delete(entry.fileId);
              }
            });
          };
        } catch (_) { /* best effort — page is being destroyed */ }
      }
    });
  }

  function save(fileId, importEntry, iconEntries) {
    if (!db) return Promise.resolve();
    return countSessionEntries(db, sessionId).then(function (count) {
      if (count >= MAX_FILES) {
        return Promise.reject(new Error('Import session full (' + MAX_FILES + ' files). Remove a file to import more.'));
      }
      var geojsonRef = importEntry.geojson;
      if (typeof DOMPurify !== 'undefined') {
        geojsonRef.features.forEach(function (f) {
          if (f.properties && f.properties.description &&
              /<[a-z][\s\S]*>/i.test(f.properties.description)) {
            f.properties.description = DOMPurify.sanitize(f.properties.description);
          }
        });
      }
      var record = {
        sessionId: sessionId,
        fileId: fileId,
        filename: importEntry.name,
        geojson: geojsonRef,
        iconEntries: iconEntries || [],
        folders: importEntry.folders,
        features: importEntry.features,
        visible: importEntry.visible,
        savedAt: Date.now()
      };
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readwrite');
        var store = tx.objectStore(STORE_NAME);
        store.put(record);
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function remove(fileId) {
    if (!db) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      store.delete(fileId);
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { reject(tx.error); };
    });
  }

  function clear() {
    if (!db) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        (req.result || []).forEach(function (entry) {
          if (entry.sessionId === sessionId) {
            store.delete(entry.fileId);
          }
        });
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      };
      req.onerror = function () { reject(req.error); };
    });
  }

  window._importStore = {
    init: init,
    save: save,
    remove: remove,
    clear: clear
  };

})();
