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

    if ('wakeLock' in navigator) {
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

  window.WakeLock = { acquire: acquire, release: release, status: status };
})();
