(function () {
  'use strict';
  if (window.WakeLock) return; // duplicate-load guard

  var shouldBeActive = false;
  var acquireGeneration = 0;
  var wakeLockSentinel = null;
  var fallbackActive = false;

  async function acquire() {
    if (shouldBeActive && (wakeLockSentinel !== null || fallbackActive)) return;
    shouldBeActive = true;
    var myGen = ++acquireGeneration;

    // iOS PWA standalone mode pre-18.4 has a non-functional wakeLock — bypass to fallback.
    var iosPwa = typeof window.matchMedia === 'function' &&
                 window.matchMedia('(display-mode: standalone)').matches;
    if ('wakeLock' in navigator && !iosPwa) {
      try {
        var sentinel = await navigator.wakeLock.request('screen');
        if (!shouldBeActive || myGen !== acquireGeneration) {
          sentinel.release().catch(function () {});
          return;
        }
        wakeLockSentinel = sentinel;
        sentinel.addEventListener('release', function () {
          if (wakeLockSentinel === sentinel) wakeLockSentinel = null;
        });
        return;
      } catch (err) {
        console.warn('[wake-lock] navigator.wakeLock.request rejected', err);
      }
    }

    // Fallback path
    if (!shouldBeActive || myGen !== acquireGeneration) return;
    if (!window.SilentVideoLock) {
      console.warn('[wake-lock] SilentVideoLock not loaded, no fallback available');
      return;
    }
    try {
      await window.SilentVideoLock.enable();
      if (!shouldBeActive || myGen !== acquireGeneration) {
        window.SilentVideoLock.disable();
        return;
      }
      fallbackActive = true;
    } catch (err) {
      console.warn('[wake-lock] SilentVideoLock.enable() rejected', err);
    }
  }

  async function release() {
    shouldBeActive = false;
    ++acquireGeneration;

    if (wakeLockSentinel !== null) {
      var s = wakeLockSentinel;
      wakeLockSentinel = null;
      try { await s.release(); } catch (err) { /* swallow */ }
    }
    if (fallbackActive) {
      fallbackActive = false;
      if (window.SilentVideoLock) {
        try { window.SilentVideoLock.disable(); } catch (err) { /* swallow */ }
      }
    }
  }

  function status() {
    if (!shouldBeActive) return 'idle';
    if (wakeLockSentinel !== null) return 'wakelock';
    if (fallbackActive) return 'fallback';
    return 'none';
  }

  document.addEventListener('visibilitychange', function () {
    if (!shouldBeActive) return;
    if (document.visibilityState !== 'visible') return;

    if ('wakeLock' in navigator && wakeLockSentinel === null) {
      var myGen = ++acquireGeneration;
      navigator.wakeLock.request('screen').then(function (s) {
        if (!shouldBeActive || myGen !== acquireGeneration) {
          s.release().catch(function () {});
          return;
        }
        wakeLockSentinel = s;
        s.addEventListener('release', function () {
          if (wakeLockSentinel === s) wakeLockSentinel = null;
        });
      }).catch(function (err) {
        console.warn('[wake-lock] visibility-re-acquire rejected', err);
      });
    }

    if (!('wakeLock' in navigator) && fallbackActive && window.SilentVideoLock) {
      if (!window.SilentVideoLock.isActive()) {
        window.SilentVideoLock.enable().catch(function () {});
      }
    }
  });

  window.WakeLock = { acquire: acquire, release: release, status: status };
})();
