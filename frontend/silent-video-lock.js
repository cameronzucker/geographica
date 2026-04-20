(function () {
  'use strict';
  if (window.SilentVideoLock) return; // duplicate-load guard

  var video = null;

  function createVideo() {
    var v = document.createElement('video');
    v.muted = true;
    v.playsInline = true;
    v.loop = true;
    v.disablePictureInPicture = true;
    v.disableRemotePlayback = true;
    v.setAttribute('aria-hidden', 'true');
    v.setAttribute('tabindex', '-1');
    v.style.cssText =
      'position:fixed;top:-9999px;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;';
    v.src = 'vendor/silent.mp4';
    return v;
  }

  function enable() {
    if (video) {
      return video.play().catch(function () {});
    }
    video = createVideo();
    document.body.appendChild(video);
    return video.play();
  }

  function disable() {
    if (!video) return;
    try { video.pause(); } catch (err) { /* ignore */ }
    video.remove();
    video = null;
  }

  function isActive() {
    return video !== null && !video.paused;
  }

  window.SilentVideoLock = { enable: enable, disable: disable, isActive: isActive };
})();
