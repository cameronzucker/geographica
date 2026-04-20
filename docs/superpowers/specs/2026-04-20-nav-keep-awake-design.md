# Nav Keep-Awake — Design Spec

**Date:** 2026-04-20
**Scope:** Prevent mobile device screen-dim / auto-lock from silently stopping turn-by-turn navigation — specifically, prevent the *driver-distraction* scenario where a silent/dim phone causes the driver to look down to investigate.
**Files:** `frontend/wake-lock.js` (new), `frontend/silent-video-lock.js` (new), `frontend/vendor/silent.mp4` (new, vendored media asset), `frontend/nav-ui.js`, `frontend/index.html`, `tests/test_wake_lock_static.py` (new Python structural tests), `frontend/tests/wake-lock/` (new JS unit tests — NOT under `tests/`), `frontend/vendor/README.md` (updated entry).
**Related:** Spec B (field-mode / Pi-as-AP) is researched separately at [dev/research/2026-04-20-spec-b-field-mode-research.md](../../../dev/research/2026-04-20-spec-b-field-mode-research.md); future voice-continuity spec ("Spec C'") will address tab-backgrounding voice-prompt reliability separately.

## Revision history

- **v2 (2026-04-20)** — Post-adversarial rewrite. Six-round review (5× Claude agents via `general-purpose`, 1× Codex v0.118.0 cross-validation) surfaced **18 MUST-FIX + 21 SHOULD-FIX** items across API correctness, concurrency safety, testing sufficiency, subagent executability, product framing, and spec-level consistency. Major structural changes:
  - **NoSleep.js dependency eliminated** (R1 F1.1, R6 F6.1). NoSleep v0.12.0 internally calls `navigator.wakeLock` first, so it was a duplicate of the primary path, not an independent fallback. Replaced with a bespoke first-party `SilentVideoLock` helper.
  - **Generation-counter race safety** in `acquire()` / `release()` (R2 F2.1/2/3/8). `release()` is now async-awaitable.
  - **Explicit accessibility contract** on the injected `<video>` (R6 F6.3).
  - **Explicit media contract** — the silent video MUST have no audio track, not merely muted silence (R6 F6.4).
  - **Explicit CSP / Permissions-Policy reservation** for the same-origin media source (R6 F6.2).
  - **Static tests use AST-ish scoped regex**, not bare `grep` (R3 F3.1, R4 F4.9).
  - **JS unit tests live at `frontend/tests/wake-lock/`**, not `tests/wake-lock/`, to avoid pytest collection collision (R3 F3.11).
  - **Safety framing** reoriented around driver distraction (R5 F5.1).
  - **Voice-continuity** elevated from buried §9 footnote to explicit out-of-scope boundary, with a sibling-spec placeholder (R5 F5.5, user decision B).
  - **Deployment / cache-busting** added (R4 F4.15).
  - Full reviews at [dev/adversarial/2026-04-20-nav-keep-awake-r{1..6}-*.md](../../../dev/adversarial/).
- **v1 (2026-04-20)** — Initial design, commit `0cfd989`. Based on NoSleep.js fallback. Invalidated by R1 discovery that NoSleep is not independent of `navigator.wakeLock`.

---

## 1. Summary

On mobile devices, Geographica's navigation mode silently breaks when the phone's screen dims or auto-locks: the browser throttles or suspends JavaScript in inactive tabs, so the GPS feed stops, voice announcements stop firing, and reroute detection stops. The driver's phone goes dark, the audio goes quiet, and **the driver looks down to check why** — the real safety hazard, in terms of eyes-off-road distraction at driving speeds.

This spec specifies a mechanism that holds the device screen awake for the duration of an active nav session, using:

- **Primary:** the W3C Screen Wake Lock API (`navigator.wakeLock`), available on Secure Context origins (HTTPS, localhost).
- **Fallback:** a small first-party `SilentVideoLock` helper that plays a silent 1×1 pixel video with no audio track, which keeps mobile browsers from dimming the screen on any origin including plain HTTP (Geographica's AREDN-mesh and Pi-hotspot paths).

The mechanism is entirely passive to the driver — no UI indicator, no audible chime, no modal, no banner. The feature is self-evidencing via the existing nav UI staying visible. When nav ends (explicit Stop, arrival auto-stop, page unload, any error path), the lock releases and normal power management resumes.

**What this spec does NOT address (explicitly out of scope, not a bug):**
- **Voice-prompt continuity during tab-backgrounding** (user answers a phone call, switches apps). That's a distinct failure mode in the voice-announcement pipeline, addressed in a separate future spec (working title: nav-voice-continuity). This spec reduces how often backgrounding happens (by keeping the screen on, drivers don't need to unlock to check the phone), which reduces the *frequency* of the voice-continuity problem — but doesn't eliminate it.
- **Offline-HTTPS infrastructure.** Tracked in Spec B.

## 2. Goals & non-goals

### Goals

- **G1.** While navigation is active, the device screen does not auto-dim or auto-lock due to idle timeout.
- **G2.** Mechanism works on both Secure Context (HTTPS/Tailscale) and plain HTTP (LAN / AREDN / future Pi-hotspot) origins.
- **G3.** Mechanism releases promptly and deterministically when navigation ends via any path.
- **G4.** Mechanism is entirely silent to the driver — no *additional* UI chrome beyond what the existing nav banner already provides. The already-visible nav banner IS the evidence that keep-awake is active; we are not adding a badge.
- **G5.** Mechanism is offline-safe — no CDN, no runtime network dependency, all assets vendored first-party.
- **G6.** Mechanism survives tab-hide / tab-show transitions (phone call, app switch, home button) without the driver taking action — on return, the lock is re-acquired automatically.
- **G7.** Module boundaries: new code lives in dedicated files (`frontend/wake-lock.js` + `frontend/silent-video-lock.js`), not in `app.js` or `nav-ui.js`. Per [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #9.
- **G8.** Race-free lifecycle: concurrent in-flight acquires, release-during-pending-acquire, and visibility-triggered re-acquires cannot orphan a wake-lock sentinel or create dual-activation (both primary + fallback held at once).
- **G9.** The injected `<video>` element imposes no accessibility burden: invisible to AT focus order, no media controls, no accessible name, no picture-in-picture or remote-playback affordance.

### Non-goals

- **NG1.** Keeping the screen at full brightness. We prevent dimming-to-off; we do not override user brightness.
- **NG2.** Preventing user-initiated screen lock (power button press).
- **NG3.** Alerting the driver when the tab is backgrounded. Audible or visual alarms during driving are rejected as hostile — the existing nav state machine's stale-GPS watchdog ([navigation.js:683](../../../frontend/navigation.js#L683)) and off-route detector ([navigation.js:633](../../../frontend/navigation.js#L633)) self-heal silently on tab return. (Caveat: a brief voice confirmation on return from *long* backgrounding may be designed in a future voice-continuity spec — this spec neither adds nor prohibits it.)
- **NG4.** A dedicated "keep-awake is on" visual indicator. The existing nav banner already serves this role.
- **NG5.** Preventing the W3C-spec-mandated release of the Wake Lock on tab-hide. That's non-negotiable; we re-acquire on tab-show.
- **NG6.** Addressing the offline-HTTPS gating problem (Device GPS, STT) — Spec B.
- **NG7.** Replaying stale voice announcements that fired during a backgrounding window. Rejected: a stale prompt is worse than silence because the turn has already happened and the information is misleading. See §9.
- **NG8.** Adding a new JS test runner toolchain. We use Node.js's built-in `node:test` module (stable since Node 20) — zero dependencies beyond Node itself.

## 3. Architecture overview

```
   ┌──────────────────────────────────────────────────────────────┐
   │  frontend/nav-ui.js startNavigation() / stopNavigation()     │
   │  — only the nav state machine knows when to call these —     │
   └──────────────┬─────────────────────────────┬─────────────────┘
                  │ acquire()                   │ release()
                  ▼                             ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  frontend/wake-lock.js (new, first-party)                    │
   │  State: shouldBeActive, acquireGeneration, wakeLockSentinel, │
   │         fallbackActive                                       │
   │  - Attempts: navigator.wakeLock.request('screen') (primary)  │
   │  - Falls through to: SilentVideoLock (fallback)              │
   │  - Re-acquires on visibilitychange when shouldBeActive       │
   │  - Idempotent; generation-counter race-safe                  │
   └──────────────┬─────────────────────────────┬─────────────────┘
                  │                             │
                  ▼ primary (Secure Context)    ▼ fallback (any origin)
   ┌──────────────────────────┐    ┌──────────────────────────────┐
   │ navigator.wakeLock       │    │ frontend/silent-video-lock.js│
   │ ('screen')               │    │ (new, first-party)           │
   │                          │    │ - Injects a 1×1 <video>      │
   │                          │    │ - Plays frontend/vendor/     │
   │                          │    │   silent.mp4 (no audio track)│
   │                          │    │ - a11y-hidden, off-screen,   │
   │                          │    │   PiP/remote disabled        │
   └──────────────────────────┘    └──────────────────────────────┘
```

The two layers are **independent**: the primary uses a browser API, the fallback uses a media element. Crucially — unlike NoSleep.js, which internally tries `navigator.wakeLock` first — the fallback never touches the Wake Lock API. If the primary rejects on a Secure Context (Low Power Mode, iOS PWA pre-18.4, permissions-policy), the fallback is a genuinely independent recovery path.

## 4. Design details

### 4.1 Primary: Screen Wake Lock API

Invocation inside `wake-lock.js`:

```js
if ('wakeLock' in navigator) {
  try {
    const sentinel = await navigator.wakeLock.request('screen');
    // race-safe handoff (see §4.3)
  } catch (err) {
    // fall through to fallback
  }
}
```

Constraints:

- **Detect via `'wakeLock' in navigator`.** Returns `false` on non-Secure-Context origins in spec-conforming browsers. Some non-conforming WebViews (Samsung Internet, in-app browsers) may expose the property but reject at call time with `NotAllowedError` — handled by the outer `try/catch`.
- **User-gesture synchronous path is preserved** for *operational* safety. The W3C Screen Wake Lock editor's draft does NOT currently require transient activation for `request()`, but (a) [w3c/screen-wake-lock#350](https://github.com/w3c/screen-wake-lock/issues/350) proposes adding that requirement in a future revision, and (b) the `<video>.play()` call in the fallback path *does* require it. We preserve the synchronous-from-click invariant for both layers.
- **Browser auto-releases on tab-hide.** The sentinel fires a `release` event. Our handler clears our reference; the visibility listener re-acquires on tab return (§4.5).
- **`request('screen')` may reject** from permissions-policy (iframe `allow` attribute missing), iOS Low Power Mode (sometimes), or tab hidden at request time. The `try/catch` handles all rejection classes uniformly.
- **iOS Home Screen PWA (standalone mode) on iOS < 18.4:** `navigator.wakeLock` is present but silently non-functional — [WebKit #254545](https://bugs.webkit.org/show_bug.cgi?id=254545). Detected at runtime and handled per §5.21.

### 4.2 Fallback: bespoke `SilentVideoLock` helper

`frontend/silent-video-lock.js` is a ~60-line first-party module. It plays a tiny silent video that keeps the mobile browser from dimming the screen, on any origin regardless of Secure Context. Replaces the (invalidated) NoSleep.js dependency from v1.

**Media contract** (mandatory — see §4.8 for full details):

- Source: `frontend/vendor/silent.mp4` — same-origin, vendored.
- **NO audio track** (not merely muted silence). `-an` flag on the ffmpeg generation command. See §4.8 for the canonical generation recipe.
- Format: H.264/MP4 (universal mobile compatibility).
- Dimensions: 1×1 pixel, 1 frame minimum, <2 KB file size.

**Element contract** (mandatory — see §4.9 for full details):

- `<video>` created programmatically, never authored in HTML.
- Properties: `muted`, `playsInline`, `loop`; `disablePictureInPicture = true`; `disableRemotePlayback = true`.
- Attributes: `aria-hidden="true"`, `tabindex="-1"`.
- No `controls`, no `title`, no `alt`, no accessible name anywhere.
- Styled off-screen: `position:fixed; top:-9999px; left:-9999px; width:1px; height:1px; opacity:0; pointer-events:none`.

**Canonical `silent-video-lock.js`:**

```js
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
      // Idempotent: re-kick play() in case the browser paused it on tab-hide.
      return video.play().catch(function () {});
    }
    video = createVideo();
    document.body.appendChild(video);
    return video.play(); // returns Promise; may reject on autoplay policy
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
```

Constraints:

- **Must be invoked from a user-gesture context.** `<video>.play()` requires transient activation. Our `acquire()` runs synchronously from the nav-start click; no `await`, no `setTimeout` between click and `enable()`.
- **iOS Low Power Mode disables `<video>` autoplay.** `enable()` rejects; `acquire()` catches it; we remain in "degraded mode" per §5.4. Battery-conscious user made their choice.
- **Same-origin asset** — requires only the default `media-src 'self'` CSP (no policy exists today; see §13 for future reservation).

### 4.3 Canonical `acquire()` / `release()` with generation-counter race safety

The canonical code below MUST be followed literally by the implementer. Deviations from the generation-counter pattern will reintroduce the orphan-lock bugs the v1 spec shipped with (R2 F2.1/2.2/2.3/2.8).

**State:**

```js
var shouldBeActive = false;       // target state
var acquireGeneration = 0;        // monotonic counter; each new acquire bumps it
var wakeLockSentinel = null;      // primary path observed state
var fallbackActive = false;       // fallback path observed state
```

**`acquire()` (async; caller fires-and-forgets):**

```js
async function acquire() {
  // Idempotency: already holding a lock → nothing to do.
  if (shouldBeActive && (wakeLockSentinel !== null || fallbackActive)) return;
  shouldBeActive = true;
  var myGen = ++acquireGeneration;

  // Primary path: Screen Wake Lock API
  if ('wakeLock' in navigator) {
    try {
      var sentinel = await navigator.wakeLock.request('screen');
      // Race check: release() or another acquire() may have run while we awaited.
      if (!shouldBeActive || myGen !== acquireGeneration) {
        sentinel.release().catch(function () {});
        return;
      }
      wakeLockSentinel = sentinel;
      sentinel.addEventListener('release', function () {
        // Only clear if THIS sentinel is still the current one (prevents
        // late release events from a stale sentinel nulling a live one).
        if (wakeLockSentinel === sentinel) wakeLockSentinel = null;
      });
      return;
    } catch (err) {
      console.warn('[wake-lock] navigator.wakeLock.request rejected', err);
      // fall through to fallback
    }
  }

  // Fallback path: bespoke SilentVideoLock
  if (!shouldBeActive || myGen !== acquireGeneration) return;
  if (!window.SilentVideoLock) {
    console.warn('[wake-lock] SilentVideoLock not loaded, no fallback available');
    return;
  }
  try {
    await window.SilentVideoLock.enable();
    // Race check again after awaited enable().
    if (!shouldBeActive || myGen !== acquireGeneration) {
      window.SilentVideoLock.disable();
      return;
    }
    fallbackActive = true;
  } catch (err) {
    console.warn('[wake-lock] SilentVideoLock.enable() rejected', err);
    // Degraded: shouldBeActive === true but no mechanism active. Per §5.4.
  }
}
```

**`release()` (async; callers may await but nav-ui.js does not):**

```js
async function release() {
  shouldBeActive = false;
  ++acquireGeneration; // invalidate any pending acquire() continuations

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
```

**Why the generation counter is load-bearing** (reproducing the v1 bug if omitted): two independent in-flight `acquire()` calls (e.g., Start → Stop → Start rapidly, or explicit click racing with visibility-triggered re-acquire) can each resolve their `request('screen')` and both store their sentinel into `wakeLockSentinel` — the later write wins and the earlier sentinel is orphaned (holds the screen on until page unload with no JS reference). The generation counter, captured locally per `acquire()` call and compared to the module-level counter on resume, detects staleness and releases the orphaned sentinel.

### 4.4 Integration points in `nav-ui.js`

Line numbers are advisory as of 2026-04-20; if they have drifted by the time of implementation, locate the hooks via the literal strings below — they are unique and stable.

**Acquire hook:** inside `function startNavigation()`, immediately after `document.body.classList.add('nav-active');`:

```js
active = true;
document.body.classList.add('nav-active');

// DO NOT insert awaited work between classList.add and primeSpeech — breaks
// the user-gesture context required by Screen Wake Lock + SpeechSynthesis.
WakeLock.acquire();

primeSpeech();
```

**Release hook:** inside `function stopNavigation()`, immediately after `document.body.classList.remove('nav-active');`:

```js
document.body.classList.remove('nav-active');

WakeLock.release();
```

**Do NOT:**

1. Move `WakeLock.acquire()` above the early-return guards (`if (!trip || !window.GeographicaNav) return;` and `if (!routeData) return;`). Those guards are intentional — if nav doesn't start, we don't want a lock held.
2. Add a call in `primeSpeech()`, `startGPSFeed()`, or any sub-operation of `startNavigation()`. The acquire call must be a statement of `startNavigation` itself.
3. Hook into `nav.onArrival()`, `nav.onReroute()`, or any engine-level callback. The release contract is tied to nav-UI lifecycle, not engine internals.
4. Wrap the acquire call in `try/catch` at the call site. Error handling lives inside `wake-lock.js`.
5. Observe `nav-active` class changes via `MutationObserver` — hook both call sites explicitly.
6. Combine `WakeLock.acquire()` with `primeSpeech()` into a single helper — they must be two separate statements.
7. Gate `WakeLock.acquire()` behind `isSecureContext` at the call site — the module itself decides which path to use.
8. Insert any line between the class toggle and `primeSpeech()` containing `await`, `fetch(`, `setTimeout(`, or `.then(`.
9. Reorder lines 161 (class add) → acquire call → 164 (primeSpeech) — this ordering is LOAD-BEARING.

### 4.5 Visibility-change handler

Attached once at module load, never detached:

```js
document.addEventListener('visibilitychange', function () {
  if (!shouldBeActive) return;                           // no nav; ignore
  if (document.visibilityState !== 'visible') return;    // going hidden; browser handles release

  // Re-acquire primary if the browser released it on tab-hide.
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

  // Fallback: re-kick only if primary is UNAVAILABLE and fallback was active.
  // Do NOT run both simultaneously — dual-activation wastes battery and can
  // create internal state drift (§5.21).
  if (!('wakeLock' in navigator) && fallbackActive && window.SilentVideoLock) {
    if (!window.SilentVideoLock.isActive()) {
      window.SilentVideoLock.enable().catch(function () {});
    }
  }
});
```

Note: `++acquireGeneration` is incremented by the visibility handler's own re-acquire so that if a user-initiated `acquire()` races with a visibility-triggered re-acquire, the generation-counter check detects the race and releases the stale sentinel.

### 4.6 Module file layout

**`frontend/wake-lock.js`** — self-contained IIFE, exports as `window.WakeLock`.

```js
(function () {
  'use strict';
  if (window.WakeLock) return; // duplicate-load guard (duplicate <script> tags,
                                // HMR, test-harness re-import)

  // ... state, acquire(), release(), status(), visibility listener ...

  window.WakeLock = { acquire: acquire, release: release, status: status };
})();
```

**`frontend/silent-video-lock.js`** — same pattern, exports as `window.SilentVideoLock`.

**`frontend/index.html`** — script tags in this order (BEFORE `nav-ui.js`):

```html
<script src="silent-video-lock.js?v=20260420"></script>
<script src="wake-lock.js?v=20260420"></script>
<!-- existing -->
<script src="navigation.js?v=20260420"></script>
<script src="nav-ui.js?v=20260420"></script>
```

See §12 for why all script tags (not just the new ones) gain the `?v=` cache-buster.

### 4.7 `status()` — diagnostic API

Returns one of four strings. Definitions are the source of truth; any test or consumer MUST use exactly these mappings.

| Return | Condition | When you see this |
|---|---|---|
| `'idle'` | `shouldBeActive === false` | Before first acquire, or after `release()` fully completes. |
| `'wakelock'` | `shouldBeActive === true && wakeLockSentinel !== null` | Primary path held a sentinel. Happy path on Secure Context. |
| `'fallback'` | `shouldBeActive === true && wakeLockSentinel === null && fallbackActive === true` | Fallback path engaged (plain HTTP or primary rejected). |
| `'none'` | `shouldBeActive === true && wakeLockSentinel === null && fallbackActive === false` | Intent-to-hold but no mechanism active. Happens in §5.4 (both paths failed), §5.18 (tab hid during pending acquire), §5.21 (iOS PWA pre-18.4), or transiently between a browser release and our re-acquire. |

### 4.8 Silent-video media contract (normative)

The vendored media asset `frontend/vendor/silent.mp4` MUST satisfy:

- **No audio track whatsoever.** Not a muted audio track — no audio stream in the container. Use `-an` on the ffmpeg generation command.
- **Codec:** H.264 (`libx264`), `pix_fmt yuv420p` for mobile compatibility.
- **Resolution:** 1×1 pixel.
- **Duration:** ≤ 1 second, single keyframe preferred.
- **Container:** MP4 with `+faststart` muxer flag.
- **File size:** < 2 KB on disk.
- **License:** MIT, generated fresh by the project (so not subject to a 3rd-party license).

**Canonical generation command** (run once; output committed):

```bash
ffmpeg -y -f lavfi -i "color=c=black:s=1x1:d=1" \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an \
  frontend/vendor/silent.mp4
```

Why "no audio track at all" matters (R6 F6.4): browsers distinguish *muted audio* from *no audio stream* in media-session routing, autoplay policy, and lock-screen affordance exposure. A muted-audio asset can: (a) unexpectedly claim the OS media session, competing with `speechSynthesis.speak()`; (b) surface a "now playing" affordance on iOS lock screens; (c) require stricter autoplay gating on some Android builds. No-audio-track eliminates all three classes of interaction.

**Verification commands** (run in test harness):

```bash
ffprobe -v error -select_streams a -show_entries stream=codec_type frontend/vendor/silent.mp4
# Expected output: empty (no audio stream present)

stat --printf="%s\n" frontend/vendor/silent.mp4
# Expected: < 2048
```

### 4.9 Accessibility contract (normative)

The `<video>` element created by `SilentVideoLock` MUST:

- Set `aria-hidden="true"`.
- Set `tabindex="-1"`.
- Have no `controls`, no `title` attribute, no inline text content, no `aria-label`, no `aria-labelledby`, no associated `<label>`.
- Have no `id` that could be referenced externally.
- Be placed outside any `<main>`, `<nav>`, `<article>`, `<section>`, or other landmark — `document.body` directly is the correct parent.
- Be CSS-positioned off-screen (`top:-9999px; left:-9999px`) and sized 1×1 with `opacity:0; pointer-events:none`.
- Disable picture-in-picture (`video.disablePictureInPicture = true`).
- Disable remote playback (`video.disableRemotePlayback = true`).

Manual acceptance step (§6.3 #6): with VoiceOver (iOS) or TalkBack (Android) active during navigation, rotor/swipe-left-right navigation MUST NOT expose a media control; tab key sequence (if a Bluetooth keyboard is present) MUST NOT focus the element. If any of these surfaces the video, fix the contract before shipping.

## 5. Failure modes and edge cases

For each, expected behavior is specified precisely.

### 5.1 `navigator.wakeLock` undefined (HTTP origin, old browser)
Detection: `!('wakeLock' in navigator)`.
Behavior: primary path is skipped (not attempted). Fallback engages.
Test: §6.2 `test_primary_unavailable_falls_to_silent_video`.

### 5.2 `navigator.wakeLock.request()` rejects synchronously or async
Causes: permissions-policy block, Low Power Mode on some browsers, tab hidden at request time, WebView non-conformance.
Behavior: caught; `console.warn`; fallback engages.
Test: §6.2 `test_primary_reject_falls_to_silent_video`.

### 5.3 `SilentVideoLock` not loaded (`window.SilentVideoLock` undefined)
Cause: script tag missing in index.html, vendor file 404, script load error.
Behavior: `console.warn`; `acquire()` returns with `shouldBeActive === true` and no mechanism active. `status() === 'none'`. Degraded: screen will dim on next idle.
Test: §6.2 `test_silent_video_lock_missing_degrades_silently`.

### 5.4 `SilentVideoLock.enable()` rejects (autoplay policy, iOS LPM, asset load failure)
Behavior: caught; `console.warn`; `fallbackActive` remains `false`; degraded per §5.3 semantics. `status() === 'none'`.
Test: §6.2 `test_silent_video_lock_enable_rejects_degrades_silently`.

### 5.5 `acquire()` called twice without intervening `release()`
Behavior: idempotent. First non-trivial completion holds; second call returns immediately at the top guard.
Test: §6.2 `test_acquire_idempotent`.

### 5.6 `release()` called before `acquire()`, or twice in a row
Behavior: idempotent. `shouldBeActive = false`; releasing null sentinel is a no-op; `fallbackActive === false` short-circuits. `status() === 'idle'` afterward.
Test: §6.2 `test_release_without_acquire_is_noop`.

### 5.7 `release()` called while `acquire()`'s primary-path `request()` is pending
Scenario: user taps Start → `request('screen')` pending → user taps Stop → `release()` runs synchronously (async release itself is fast) → eventually primary Promise resolves.
Behavior: the generation-counter check in `acquire()` resume detects `myGen !== acquireGeneration` (because `release()` bumped the generation), releases the resolved sentinel, exits. No orphan.
Test: §6.2 `test_release_during_pending_primary_releases_sentinel`.

### 5.8 `release()` called while `acquire()`'s fallback-path `enable()` is pending
Scenario: primary unavailable → fallback `enable()` Promise pending → `release()` runs.
Behavior: same structure as §5.7 — generation-counter check in fallback branch detects staleness, calls `SilentVideoLock.disable()`, exits.
Test: §6.2 `test_release_during_pending_fallback_disables_video`.

### 5.9 Tab hidden during active nav (phone call, app switch)
Behavior: browser auto-releases the primary sentinel and fires `release` event; our handler clears `wakeLockSentinel`. Browser may pause the fallback `<video>`. `shouldBeActive` remains `true`.
On tab return: visibility handler re-acquires primary (generation-safe); or re-kicks fallback if primary is unavailable.
Test: §6.2 `test_visibility_hidden_then_visible_reacquires`.

### 5.10 Rapid Start → Stop → Start with the first primary `request()` still pending
Scenario: user taps Start → Stop → Start in quick succession while the first `request()` is still in flight.
Behavior: each call bumps the generation. The first pending Promise, when it resolves, sees a stale generation and releases its sentinel. The third call's Promise, when it resolves, installs its sentinel correctly.
Test: §6.2 `test_rapid_start_stop_start_no_orphan_sentinel`.

### 5.11 Visibility-triggered re-acquire races with explicit `release()`
Scenario: tab returns to visible → visibility handler starts `request()` → user taps Stop before resolve → `release()` bumps generation.
Behavior: pending visibility-path `request()` sees stale generation on resolve, releases its sentinel. `release()` completes cleanly. No orphan.
Test: §6.2 `test_visibility_reacquire_race_with_release`.

### 5.12 `release` event fires after our own explicit `release()`
Scenario: `release()` sets `wakeLockSentinel = null` and awaits `s.release()`; browser also fires `release` event on `s` asynchronously.
Behavior: handler compares `wakeLockSentinel === s`; `wakeLockSentinel` is already null (or is a new sentinel from a subsequent acquire). No-op. No stomping of a newer sentinel.
Test: §6.2 `test_stale_release_event_does_not_null_current_sentinel`.

### 5.13 Off-route reroute in progress (up to 10 s)
Behavior: wake-lock unaffected. Lock held throughout the reroute window.
Test: §6.2 `test_reroute_keeps_lock`.

### 5.14 Arrival → 3-second auto-stop delay
Behavior: wake-lock unaffected during the 3-second delay; `release()` fires when `stopNavigation()` runs.
Test: §6.2 `test_arrival_delay_keeps_lock_until_stop` using `t.mock.timers.tick(3000)`.

### 5.15 User explicitly taps Stop
Behavior: `stopNavigation()` → `release()`. Standard path.
Test: §6.2 `test_explicit_stop_releases_lock`.

### 5.16 `nav-active` class manipulated by external code (MutationObserver attacks)
Behavior: our hooks fire only from `startNavigation()` / `stopNavigation()`, not from class-change observation. Direct class manipulation does NOT trigger acquire/release.
Test: §6.2 `test_class_manipulation_does_not_trigger_acquire`.

### 5.17 Multiple tabs of Geographica open simultaneously
Behavior: each tab holds its own independent wake-lock. Browsers permit per-document locks. Acceptable.
Verification: manual (§6.3); not unit-testable.

### 5.18 Tab hidden DURING pending `acquire()`'s primary `request()`
Scenario: user taps Start → request pending → tab hidden (home button in the <50 ms window) → request rejects with `NotAllowedError`.
Behavior: fallback `enable()` is called on a hidden tab; autoplay policy may reject. Caught per §5.4. State: `shouldBeActive === true`, no mechanism, `status() === 'none'`. On tab return, visibility handler re-acquires primary successfully.
Test: §6.2 `test_tab_hidden_during_pending_acquire`.

### 5.19 iOS Low Power Mode
Behavior: primary `navigator.wakeLock.request()` may succeed, fail silently, or reject; fallback `<video>.play()` is blocked by LPM's autoplay restrictions. Worst case: both paths fail per §5.3/5.4.
**Documented degradation.** User has explicitly prioritized battery. Release notes MUST call this out (§10 item 10).
Test: §6.2 `test_both_paths_fail_status_is_none`.

### 5.20 Browser permissions-policy or iframe embedding blocks `wakeLock`
Behavior: rejects with `NotAllowedError`. Falls through to fallback per §5.2.
Test: covered by §5.2's test.

### 5.21 iOS Home Screen PWA on iOS < 18.4 (WebKit #254545)
Scenario: user added Geographica to Home Screen; runs in standalone mode; `navigator.wakeLock` is exposed but silently non-functional. `request()` resolves with a sentinel that does not actually hold the screen awake.
Detection: `window.matchMedia('(display-mode: standalone)').matches === true` AND iOS Safari UA. If both, bypass primary and go straight to fallback.
Implementation: one-line check at the top of the primary-path `if ('wakeLock' in navigator)` block, treating standalone-mode iOS as if the API were absent.
Test: §6.2 `test_ios_pwa_standalone_bypasses_primary`.

### 5.22 Module loaded twice (duplicate `<script>` tag, HMR, test re-import)
Behavior: IIFE top guard `if (window.WakeLock) return;` short-circuits subsequent loads. State owned by the first closure, never duplicated.
Test: §6.2 `test_duplicate_module_load_is_noop`.

## 6. Testing strategy

Three layers. No new test runner toolchain.

### 6.1 Python structural tests — `tests/test_wake_lock_static.py`

Verifies file/structural invariants. Each test goes beyond `"string in file"` greps by scoping to specific functions and checking AST-like patterns.

**Canonical static-test helper pattern** (shared in `conftest.py` or inline in the test file):

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def read(p):
    return (ROOT / p).read_text(encoding='utf-8')

def function_body(src: str, func_decl: str) -> str:
    """Return the body of a function declaration in JS source, tracking braces."""
    idx = src.index(func_decl)
    start = src.index('{', idx) + 1
    depth = 1
    i = start
    while depth > 0 and i < len(src):
        c = src[i]
        if c == '{': depth += 1
        elif c == '}': depth -= 1
        i += 1
    return src[start:i-1]

def strip_comments_and_strings(src: str) -> str:
    """Remove JS line/block comments and string literals to avoid false grep hits."""
    src = re.sub(r'//.*?$', '', src, flags=re.MULTILINE)
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.DOTALL)
    src = re.sub(r'"(?:\\.|[^"\\])*"', '""', src)
    src = re.sub(r"'(?:\\.|[^'\\])*'", "''", src)
    src = re.sub(r'`(?:\\.|[^`\\])*`', '``', src)
    return src
```

**Tests (each is a single `def test_...` function):**

1. `test_silent_mp4_vendored_with_correct_properties` — asserts `frontend/vendor/silent.mp4` exists, size < 2 KB, and contains no audio stream (spawn `ffprobe`; if not installed, skip with reason).
2. `test_silent_video_lock_js_exists_and_exports_api` — parse `frontend/silent-video-lock.js`; assert an IIFE top-level guard (`if (window.SilentVideoLock) return;`) and that `window.SilentVideoLock = { ... }` literal contains `enable`, `disable`, `isActive` keys (regex after strip_comments_and_strings).
3. `test_wake_lock_js_exists_and_exports_api` — same pattern; assert `enable`-ish pattern; top-level guard `if (window.WakeLock) return;`; `window.WakeLock = { ... }` contains `acquire`, `release`, `status`.
4. `test_wake_lock_uses_generation_counter` — parse `frontend/wake-lock.js`; assert `acquireGeneration` and `myGen` tokens appear in the body of `acquire()` and `release()` (scoped via `function_body`). This catches a subagent who deletes the race-safety pattern.
5. `test_index_html_loads_scripts_in_correct_order` — parse index.html; find `<script src=...>` tags; assert `silent-video-lock.js` appears before `wake-lock.js` appears before `nav-ui.js`.
6. `test_index_html_scripts_have_cache_buster` — assert every script tag touched by this feature has `?v=` query string (per §12).
7. `test_nav_ui_acquires_wake_lock_in_start_navigation` — parse `frontend/nav-ui.js`; extract `function startNavigation()` body via `function_body`; strip comments/strings; assert `WakeLock.acquire()` appears exactly once; assert no `await` / `fetch(` / `setTimeout(` / `.then(` token appears BEFORE it in the function body; assert the immediately-preceding non-blank line contains `document.body.classList.add('nav-active')`.
8. `test_nav_ui_releases_wake_lock_in_stop_navigation` — same pattern for `stopNavigation` / `WakeLock.release()` / `classList.remove`.
9. `test_no_nosleep_references_remain` — assert no occurrence of `NoSleep` (case-insensitive) anywhere under `frontend/` — prevents the invalidated v1 design from sneaking back in.
10. `test_no_cdn_urls_for_media_assets` — assert no `unpkg.com`, `cdn.jsdelivr.net`, or `cdnjs.cloudflare.com` references in frontend/wake-lock.js, silent-video-lock.js, or index.html (per [implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #6 offline-first).
11. `test_vendor_readme_lists_silent_mp4` — assert `frontend/vendor/README.md` table has a row for `silent.mp4` naming its purpose (per R4 F4.5).
12. `test_silent_video_lock_sets_accessibility_attributes` — parse `frontend/silent-video-lock.js`; assert source contains `aria-hidden`, `tabindex`, `disablePictureInPicture`, `disableRemotePlayback` (each as a token).

### 6.2 JS unit tests — `frontend/tests/wake-lock/` using `node:test`

**NOT under `tests/`** to avoid pytest collection. Directory must be `frontend/tests/wake-lock/` (hyphen intentional; not a Python-importable name).

**Reference mock factories** — single source of truth, every test uses these:

```js
// frontend/tests/wake-lock/_fixtures.js
import { mock } from 'node:test';

export function makeSentinelMock() {
  const listeners = Object.create(null);
  const sentinel = {
    type: 'screen',
    released: false,
    release: mock.fn(() => {
      sentinel.released = true;
      (listeners.release || []).forEach(cb => cb());
      return Promise.resolve();
    }),
    addEventListener: (name, cb) => {
      (listeners[name] = listeners[name] || []).push(cb);
    },
    removeEventListener: () => {},
    _fire: (name) => { (listeners[name] || []).forEach(cb => cb()); },
    _listeners: listeners,
  };
  return sentinel;
}

export function makeWakeLockNavigatorMock({ rejectWith } = {}) {
  return {
    request: mock.fn((type) => {
      if (rejectWith) return Promise.reject(rejectWith);
      return Promise.resolve(makeSentinelMock());
    }),
  };
}

export function makeSilentVideoLockMock({ rejectWith } = {}) {
  const m = {
    _active: false,
    enable: mock.fn(() => {
      if (rejectWith) return Promise.reject(rejectWith);
      m._active = true;
      return Promise.resolve();
    }),
    disable: mock.fn(() => { m._active = false; }),
    isActive: mock.fn(() => m._active),
  };
  return m;
}

export function makeDocumentMock() {
  const listeners = Object.create(null);
  const doc = {
    visibilityState: 'visible',
    hidden: false,
    addEventListener: (name, cb) => {
      (listeners[name] = listeners[name] || []).push(cb);
    },
    removeEventListener: () => {},
    body: {
      appendChild: mock.fn(),
      classList: { add: mock.fn(), remove: mock.fn() },
    },
    createElement: mock.fn((tag) => ({
      setAttribute: mock.fn(),
      style: { cssText: '' },
      play: mock.fn(() => Promise.resolve()),
      pause: mock.fn(),
      remove: mock.fn(),
      paused: false,
    })),
    _fire: (name) => { (listeners[name] || []).forEach(cb => cb()); },
  };
  return doc;
}
```

**Tests** — one per failure mode in §5. Each test uses `vm.runInNewContext` to load `wake-lock.js` into a constructed global with the mock fixtures above, then exercises the module.

Named tests with expected assertion sketches:

1. `test_primary_available_acquires_wakelock` — primary works. Assert: `navigator.wakeLock.request.mock.callCount === 1`, `status() === 'wakelock'`, `SilentVideoLock.enable.mock.callCount === 0`.
2. `test_primary_unavailable_falls_to_silent_video` (§5.1) — omit `navigator.wakeLock`. Assert: `SilentVideoLock.enable.mock.callCount === 1`, `status() === 'fallback'`.
3. `test_primary_reject_falls_to_silent_video` (§5.2) — `makeWakeLockNavigatorMock({ rejectWith: new Error('NotAllowedError') })`. Assert: `SilentVideoLock.enable.mock.callCount === 1`, `status() === 'fallback'`.
4. `test_silent_video_lock_missing_degrades_silently` (§5.3) — omit `window.SilentVideoLock`, omit primary. Assert: `status() === 'none'`, no throws.
5. `test_silent_video_lock_enable_rejects_degrades_silently` (§5.4) — omit primary; fallback rejects. Assert: `status() === 'none'`, `SilentVideoLock._active === false`.
6. `test_acquire_idempotent` (§5.5) — call acquire() twice. Assert: `navigator.wakeLock.request.mock.callCount === 1`.
7. `test_release_without_acquire_is_noop` (§5.6) — release() first. Assert: no throws, `status() === 'idle'`.
8. `test_release_during_pending_primary_releases_sentinel` (§5.7) — delayed-resolve primary mock; acquire; release; resolve. Assert: returned sentinel's `release.mock.callCount === 1`, `wakeLockSentinel === null`.
9. `test_release_during_pending_fallback_disables_video` (§5.8) — no primary; delayed-resolve fallback; acquire; release; resolve. Assert: `SilentVideoLock.disable.mock.callCount === 1`, `status() === 'idle'`.
10. `test_visibility_hidden_then_visible_reacquires` (§5.9) — acquire; fire visibility hidden; browser fires sentinel release event; fire visibility visible. Assert: second `request()` call, new sentinel installed, `status() === 'wakelock'`.
11. `test_rapid_start_stop_start_no_orphan_sentinel` (§5.10) — delayed-resolve primary; acquire; release; acquire; resolve both. Assert: first sentinel's `release.mock.callCount === 1` (orphan cleanup); final `wakeLockSentinel` is the second sentinel.
12. `test_visibility_reacquire_race_with_release` (§5.11) — fire hidden; fire visible (triggers re-acquire Promise); release() before resolve; resolve. Assert: re-acquired sentinel's `release.mock.callCount === 1`, final state is `'idle'`.
13. `test_stale_release_event_does_not_null_current_sentinel` (§5.12) — acquire; manually fire release on the first sentinel after a second acquire. Assert: `wakeLockSentinel` points to the newer sentinel.
14. `test_reroute_keeps_lock` (§5.13) — acquire; simulate reroute callback; verify lock still held.
15. `test_arrival_delay_keeps_lock_until_stop` (§5.14) — `t.mock.timers.enable({ apis: ['setTimeout'] })`; acquire; fire arrival; `t.mock.timers.tick(3000)`; stopNavigation-equivalent. Assert: lock held across the tick; released after.
16. `test_explicit_stop_releases_lock` (§5.15) — acquire; release. Assert: `sentinel.release.mock.callCount === 1`, `status() === 'idle'`, AND `SilentVideoLock.enable.mock.callCount === 0` (negative invariant: fallback NOT called when primary succeeded).
17. `test_class_manipulation_does_not_trigger_acquire` (§5.16) — manually toggle `document.body.classList` without calling nav-ui; assert `navigator.wakeLock.request.mock.callCount === 0`.
18. `test_tab_hidden_during_pending_acquire` (§5.18) — primary request pending; fire visibility-hidden; mock request to reject with NotAllowedError; verify fallback path engaged or degraded cleanly.
19. `test_both_paths_fail_status_is_none` (§5.19 — LPM combined failure) — primary rejects, fallback rejects. Assert: no throws, `status() === 'none'`.
20. `test_ios_pwa_standalone_bypasses_primary` (§5.21) — mock `window.matchMedia('(display-mode: standalone)')` to match; primary path SKIPPED; fallback invoked. Assert: `navigator.wakeLock.request.mock.callCount === 0`, `SilentVideoLock.enable.mock.callCount === 1`.
21. `test_duplicate_module_load_is_noop` (§5.22) — load wake-lock.js twice in same context; assert state preserved, single listener.

Each test runs in < 150 ms; total suite < 3 s.

### 6.3 Manual field acceptance

Executed by Cameron on real phones (agent-complete ≠ ship-complete — see §10 item 8). Each line numbered; attach evidence to the PR body per CONTRIBUTING.md gate (see §10 item 11).

1. **HTTPS primary path.** Open Geographica over Tailscale. Start nav to a nearby destination. Set phone down without interacting. Screen MUST stay on until nav ends.
2. **HTTP fallback path.** Open Geographica over LAN (HTTP). Repeat test 1. Screen MUST stay on (via silent-video fallback).
3. **Phone-call interruption.** Start nav over HTTPS. Receive a phone call. Answer and end the call. Return to Geographica. Screen MUST still be on; nav MUST continue without user intervention.
4. **Arrival.** Let nav complete to destination. Arrival banner MUST stay visible for 3 seconds with the screen still on; after auto-stop, screen MUST resume normal auto-dim behavior.
5. **iOS Low Power Mode (documented degradation).** Enable LPM; start nav. Expected behavior: the feature may silently no-op; screen may dim on normal idle timeout. No crashes, no console errors. Note observed behavior in PR body.
6. **Screen-reader coexistence (a11y).** Enable VoiceOver (iOS) or TalkBack (Android). Start nav. Navigate via rotor/swipe. MUST NOT surface an unlabeled media control. Must not disrupt voice-announcement audio.
7. **Voice-TTS coexistence with fallback.** Start nav over HTTP (forces fallback video active). Wait for the first voice prompt. Voice MUST fire normally through the phone speaker while the silent video plays.
8. **Voice-TTS coexistence with STT (if applicable).** Over HTTPS, start nav; trigger STT voice search while the fallback is active. STT start/stop MUST work; nav voice prompts MUST continue.
9. **Battery cost (informational).** Run a 30-minute nav session on the fallback path with the screen on; record battery drop. Compare to baseline (nav off). If delta exceeds 15 %/hour, file a performance follow-up.
10. **Duplicate-tab behavior.** Open Geographica in two tabs; start nav in both. Both screens should stay on independently. Close one; the other continues.

### 6.4 CI-level smoke test (Playwright, optional but strongly recommended)

One Playwright test in `frontend/tests/wake-lock/playwright/`:

```js
// Load the frontend on http://localhost, click Start-Nav, evaluate
// `await navigator.wakeLock.request('screen').then(s => !s.released)` —
// asserts Chromium granted a lock (closest-to-behavior CI check short of
// a real phone).
```

Not a blocker for initial ship; add as follow-up if the full Playwright harness comes online.

## 7. Pitfalls addressed

| Pitfall | How this spec addresses it |
|---------|----------------------------|
| [implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #5 (HTTPS requirement for browser APIs) | Dual-path design: `navigator.wakeLock` on Secure Context, bespoke silent-video fallback on HTTP. The fallback is truly independent (no shared internal API calls with the primary). |
| [implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #6 (Offline-first design) | No CDN references. Silent-video asset is vendored at `frontend/vendor/silent.mp4`, verified absent from any CDN URL by static test. |
| [implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #9 (Frontend module boundaries) | New code in dedicated files. `nav-ui.js` gets exactly two new one-line calls. |
| [testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) #9 (Unrecoverable async state) | Generation counter + explicit release checks at every await resume point. Dedicated tests for release-during-pending-primary AND release-during-pending-fallback. |
| [testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) #10 (JS truthiness for numeric zero) | State checks use explicit `=== null` and `=== 0` comparisons, never `||`. |
| [testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) #11 (Duplicated logic) | Wake-lock module is the sole authority on lock state. `nav-ui.js` does not mirror or track it. |

## 8. Dependencies

- **No third-party JS dependencies.** NoSleep.js from v1 is REMOVED — it was shown by R1 F1.1 to be a duplicate of the primary path, not an independent fallback.
- **Node.js ≥ 18** for JS unit tests via the built-in `node:test` module. This project's dev Pi is on Node v20.19.2 (verified at spec time). CI and LXD harness images must provide Node ≥ 18. Python's stdlib is sufficient for the static tests — no new Python dependencies.
- **ffmpeg** — required at vendor-generation time to produce `silent.mp4` (one-time, committed output). Not a runtime dependency.
- **ffprobe** — used by one static test for audio-track assertion; if unavailable, the test skips with a clear reason (not a hard blocker).

## 9. Out of scope / deferred

- **OS1.** Spec B (field-mode / Pi-as-AP). Research complete at [dev/research/2026-04-20-spec-b-field-mode-research.md](../../../dev/research/2026-04-20-spec-b-field-mode-research.md); brainstorm deferred.
- **OS2.** Offline-HTTPS story generally (CA install flows, nginx multi-listener refactor). Belongs to Spec B.
- **OS3.** **Voice-prompt continuity during tab-backgrounding.** Explicit out-of-scope per user decision. When the nav tab is backgrounded (phone call, app switch), browsers may throttle or suspend `speechSynthesis.speak()` dispatches, causing voice announcements to be dropped or delayed. Wake-lock reduces the *frequency* of backgrounding (by preventing the user from having to unlock the phone to check it) but does not eliminate user-initiated backgrounding. Replaying stale announcements is explicitly rejected (NG7) — a stale prompt is worse than silence. A proper fix requires mechanisms like a silent audio element or the Media Session API to keep `speechSynthesis` reliable during backgrounding. Deferred to a future voice-continuity spec (working title: nav-voice-continuity). The manual acceptance checks in §6.3 #7 and #8 verify the baseline behavior *while the tab is active*; post-backgrounding behavior is unverified by this spec and left to field experience.
- **OS4.** Release of wake-lock on specific edge cases beyond the primary lifecycle (e.g., long-idle, battery-state changes). Not needed — simpler is correct.
- **OS5.** Structured telemetry / debug overlay for wake-lock failures. `console.warn` is sufficient for beta-tester debugging.

## 10. Acceptance criteria (checklist)

Each item maps to a phase-success-criterion in the implementation plan. Item 8 (manual) is deferred to Cameron per §6.3 and is NOT a blocker for agent-complete sign-off.

- [ ] 1. `frontend/vendor/silent.mp4` is committed, ≤ 2 KB, verified by `ffprobe` to have no audio stream.
- [ ] 2. `frontend/silent-video-lock.js` implements the contract in §4.2 + §4.8 + §4.9.
- [ ] 3. `frontend/wake-lock.js` implements the canonical `acquire()` / `release()` from §4.3, including the generation counter; implements the visibility handler from §4.5; implements `status()` per §4.7.
- [ ] 4. `frontend/index.html` loads `silent-video-lock.js` before `wake-lock.js` before `nav-ui.js`, with cache-busting query strings per §12.
- [ ] 5. `nav-ui.js` calls `WakeLock.acquire()` inside `startNavigation()`, on the line immediately following `document.body.classList.add('nav-active')`, synchronously, with the load-bearing comment above it from §4.4.
- [ ] 6. `nav-ui.js` calls `WakeLock.release()` inside `stopNavigation()`, on the line immediately following `document.body.classList.remove('nav-active')`.
- [ ] 7. All 12 Python static tests in `tests/test_wake_lock_static.py` pass (§6.1).
- [ ] 8. All 21 JS unit tests in `frontend/tests/wake-lock/` pass under `node --test frontend/tests/wake-lock/` (§6.2).
- [ ] 9. `frontend/vendor/README.md` lists `silent.mp4` with MIT license and purpose line.
- [ ] 10. CHANGELOG.md entry written describing the fix and known limitations: "On iOS, Low Power Mode may disable the screen keep-awake feature. Disable Low Power Mode or keep the phone plugged in for uninterrupted navigation."
- [ ] 11. CONTRIBUTING.md gate line added: "Changes to `frontend/wake-lock.js`, `frontend/silent-video-lock.js`, `frontend/vendor/silent.mp4`, or the hook lines in `frontend/nav-ui.js` require §6.3 manual re-run with screenshot/video evidence attached to the PR body."
- [ ] 12. No regressions in `python -m pytest tests/ -v` AND `node --test frontend/tests/wake-lock/` — both suites green.
- [ ] 13. No new `console.error` output during normal nav operation on HTTPS or HTTP. (`console.warn` in degraded paths is expected per §5.)
- [ ] 14. **Manual field acceptance checklist (§6.3) — DEFERRED to Cameron.** Agent-complete ≠ ship-complete. When items 1-13 are green, agent work terminates and the plan produces a PR with §6.3 as a checklist embedded in the PR body. Cameron runs §6.3 on real phones; until that passes, the feature is "code-complete, field-untested." Do NOT mark this item complete in an agent-driven workflow; it exists to make the human handoff explicit.

## 11. Open questions

None as of v2. (All v2 revisions close out v1's open questions and the 39 adversarial findings.)

## 12. Deployment

No Docker rebuild is required — the frontend is served statically by nginx from the bind-mounted `frontend/` directory. However:

- **nginx caching.** `nginx/nginx.conf` sets no explicit `Cache-Control` or `Expires` for static files; default is heuristic caching. Browser clients (including beta testers with warm caches) may hold stale `index.html` for up to several hours.
- **Cache-busting.** To ensure new script tags load on already-warm client caches, every script tag in `index.html` touched by this change (the two new ones AND any existing ones you're editing) gets a `?v=20260420` query string. Nginx passes the query through transparently; browsers treat the URL as new.
- **`sub_filter` scope.** nginx's `sub_filter` directive applies ONLY to `application/json` and `text/plain` MIME types (verified in `nginx/nginx.conf`). It does NOT touch `<script src>` URLs in `text/html` responses. No escaping concerns.

Deployment steps (manual or via `git pull` on the Pi):

```bash
# On the Pi:
cd /home/administrator/Code/geographica
git pull origin main          # pulls the new frontend/ files
# No docker rebuild needed — bind mount picks up new files automatically.
# Verify nginx is serving them:
curl -sI https://pandora.twin-bramble.ts.net/wake-lock.js | head -5
# Expect: 200 OK
```

If running locally during development, the bind mount means no restart is needed at all — refresh the browser.

## 13. Browser-policy compatibility

Geographica's `nginx/nginx.conf` currently sets **no** `Content-Security-Policy` or `Permissions-Policy` headers. This spec documents forward-compat requirements so a future hardening pass doesn't silently regress the HTTP fallback path — which is the *primary* wake-lock path for AREDN-mesh and Pi-hotspot deployments.

**If CSP is added in the future, the minimum directives for this feature are:**

- `script-src 'self'` (no inline scripts introduced; wake-lock.js and silent-video-lock.js are external files).
- `media-src 'self'` (the silent video is a same-origin asset; we do NOT use a `data:` URL). Do NOT require `'unsafe-inline'`, `data:`, or `blob:`.

**Do NOT switch `silent.mp4` to a `data:` URL in the future without also:**
- Adding `data:` to `media-src`, AND
- Updating this §13 to document the change, AND
- Re-running all §6.3 tests.

**If iframe embedding of Geographica is ever supported**, the host page's `<iframe allow="...">` attribute must include both `screen-wake-lock` (for the primary path) and `autoplay` (for the fallback path). Without either, the feature silently degrades. Currently, Geographica is not embedded; this is a note for the future.

**Regression assertion:** any future PR touching `nginx/nginx.conf` that introduces `Content-Security-Policy` or `Permissions-Policy` headers MUST re-run §6.3 tests 1 and 2 (HTTPS primary, HTTP fallback) to confirm neither path silently broke.

---

## Appendix A — Silent video media asset

Generated fresh for this project using ffmpeg (see §4.8 for the canonical command). License: MIT (same as the Geographica project). Committed at `frontend/vendor/silent.mp4`.

Why a bespoke first-party asset rather than a third-party library:
- Eliminates a 5-year-unmaintained dependency (NoSleep.js v0.12.0, Dec 2020, no releases since).
- Removes the redundant primary-path call inside NoSleep (R1 F1.1).
- Gives us exact control over the media contract (no audio track per R6 F6.4).
- Trivial to audit, replace, or regenerate.

Regenerate with:

```bash
ffmpeg -y -f lavfi -i "color=c=black:s=1x1:d=1" \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an \
  frontend/vendor/silent.mp4
# Verify:
ffprobe -v error -select_streams a -show_entries stream=codec_type frontend/vendor/silent.mp4  # must be empty
stat --printf="%s\n" frontend/vendor/silent.mp4                                                  # must be < 2048
```

## Appendix B — Why only `'screen'` wake lock type

The W3C Screen Wake Lock Level 1 spec defines exactly one type: `'screen'`. A proposed `'system'` type was deprecated; `'video'` was never standardized. Use `'screen'` exclusively.

## Appendix C — Why not gate on battery state

Some patterns suggest gating wake-lock on `navigator.getBattery()` state (e.g., skip if battery < 20 %). This is rejected: a driver in the field may be on low battery *and still need nav*. The user chose to start nav; respect that choice. Do not gate wake-lock on battery state.

## Appendix D — W3C Wake Lock transient-activation status

The W3C Screen Wake Lock Level 1 editor's draft does NOT currently require transient activation for `request('screen')`. However, [w3c/screen-wake-lock#350](https://github.com/w3c/screen-wake-lock/issues/350) (open since 2022) proposes adding that requirement. Regardless of the eventual outcome, we preserve the user-gesture-synchronous invocation path because:
- `<video>.play()` in the fallback DOES require transient activation.
- Future-proofing against the proposed W3C change.
- Consistent mental model for implementers.

## Appendix E — Review trail

Full adversarial reviews: [dev/adversarial/2026-04-20-nav-keep-awake-r{1..6}-*.md](../../../dev/adversarial/).
Round 1 was the highest-impact round (invalidated the NoSleep.js architecture); Round 2 found the generation-counter-necessary race; Round 6 (Codex) caught the spec-meta coherence gap that R1-R5 collectively missed. The review trail is preserved uncommitted for the spec's future evolution.
