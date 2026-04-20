---
round: 1
angle: Browser API correctness
reviewer: general-purpose (Codex substitute — env has no Codex access)
date: 2026-04-20
---

# Round 1 — Browser API correctness

Verified spec claims against the W3C Screen Wake Lock Level 1 editor's
draft, MDN, the actual NoSleep.js v0.12.0 dist source, and public browser
bug trackers. Findings below are keyed to the attack angles in the
assignment.

## Findings

### F1.1 — NoSleep.js v0.12.0 already uses `navigator.wakeLock` internally; the spec's "primary vs fallback" architecture is partly redundant and double-acquires on Secure Context
**Severity:** MUST-FIX
**Claim in spec:** §3 diagram and §4 describe two independent layers:
"Primary: `navigator.wakeLock`" and "Fallback: NoSleep.js (silent-video
autoplay)." §4.3 `acquire()` tries `navigator.wakeLock.request('screen')`
first, then falls through to `noSleep.enable()` on reject.
**Reality:** NoSleep.js v0.12.0's own `enable()` calls
`navigator.wakeLock.request("screen")` first when available, and only
falls through to the silent-`<video>` autoplay trick when the API is
missing. That's visible in the dist source on the `master` branch — the
first branch of `enable()` reads:

```js
if ("wakeLock" in navigator) {
  return navigator.wakeLock.request("screen").then(function (wakeLock) {
    _this2._wakeLock = wakeLock;
    _this2.enabled = true;
  });
}
```

So the spec's `acquire()` flow on a Secure Context where
`navigator.wakeLock.request` rejects (e.g., Low Power Mode, permissions
policy, tab hidden at request time) will then call `noSleep.enable()`,
which will turn around and call `navigator.wakeLock.request('screen')`
*again* — same rejection, same `NotAllowedError`, and *then* NoSleep's
own internal fallback never runs because NoSleep only reaches the
`<video>` path when `"wakeLock" in navigator` is false.

Net: on HTTPS with Low Power Mode or hidden-tab rejection, we lose the
`<video>` fallback we think we have. On HTTPS on an iOS PWA pre-18.4,
same problem. The two layers are not independent; they share a trunk.
**Impact:** Loss of fallback exactly in the cases the spec names as
motivating the fallback (§5.4, §5.16). This is the central design claim,
and it's wrong.
**Proposed fix:** Either (a) on rejection of the primary path, set a
flag that forces NoSleep to use its video path (NoSleep exposes no such
flag — would need a source patch or a fork); or (b) skip NoSleep and
instead bundle a small purpose-built silent-`<video>`-autoplay helper
that unconditionally uses the video path, never the Wake Lock API.
Option (b) is cleaner and removes NoSleep as a dependency we can't
control. Either way, update §3/§4 to reflect that the two layers share
the same primary call path in NoSleep's current form.
**Sources:** https://github.com/richtr/NoSleep.js/blob/master/dist/NoSleep.js

### F1.2 — iOS Safari < 18.4 does not support `navigator.wakeLock` in Home Screen PWAs; spec is silent on PWA-mode detection
**Severity:** SHOULD-FIX
**Claim in spec:** §4.1 "Must be Secure Context. `navigator.wakeLock` is
undefined on plain HTTP. Detection is via `'wakeLock' in navigator`."
Spec treats presence of the property as sufficient.
**Reality:** On iOS 16.4 – 18.3, Safari exposes `navigator.wakeLock` in
browser mode but the API silently fails when the site is launched as a
Home Screen Web App (added to Home Screen). WebKit bug 254545 tracked
this for ~24 months and was only fixed in iOS/iPadOS 18.4 (March 2025).
A user population running iOS 17.x or 18.0–18.3 added Geographica to
their home screen will get a truthy `'wakeLock' in navigator` check, a
resolved `request('screen')` promise in some cases, and no actual screen
lock. The fallback never triggers because the primary "succeeded."
**Impact:** Silent failure on a real user segment. Driver puts phone
down, screen dims, nav stalls, spec's §1 safety-of-life scenario
materializes.
**Proposed fix:** Either accept it as documented degradation (add to
§5.16 / §5 failure modes explicitly), or detect standalone-mode
(`window.matchMedia('(display-mode: standalone)').matches ||
navigator.standalone`) on iOS and force the NoSleep video path. Given
§1's safety framing, the latter is the honest choice.
**Sources:** https://bugs.webkit.org/show_bug.cgi?id=254545,
https://github.com/richtr/NoSleep.js/issues/156

### F1.3 — Claim that user-gesture grace window is required by the W3C spec is not quite right
**Severity:** NICE-TO-HAVE
**Claim in spec:** §4.1 / §4.2 / §4.4 / §10 all assert that
`request('screen')` "must be called from a user gesture context" and the
"gesture grace window" must be preserved across the await. §4.3 §4.4 go
further: "Must be called BEFORE any awaited promise or
setTimeout/setInterval."
**Reality:** The current W3C editor's draft does *not* require transient
activation for `navigator.wakeLock.request('screen')`. The request
algorithm checks (a) document fully active, (b) visibility !== hidden,
(c) Permissions Policy allows the feature, (d) user agent not denying,
(e) permission grant. There is a W3C issue (#350, open since 2022)
proposing to require transient activation; it has not landed in the
spec. Shipping browsers (Chrome, Firefox, Safari) do not currently
require transient activation for the screen wake lock either — only for
the dialog-spawning permission prompt, which in practice doesn't prompt
for screen wake lock in any browser today (it's treated as auto-granted
when the document is visible).

The `<video>.play()` path NoSleep uses *does* require transient
activation or an autoplay-allowed policy — so the "user gesture" mental
model is right for *NoSleep's fallback*, wrong for the Wake Lock API
itself.
**Impact:** Design is over-constrained. §4.4's prohibition on awaiting
before the acquire call is defensible as a belt-and-suspenders measure
(particularly for the NoSleep fallback), but the rationale is
misattributed. Low risk — the resulting code pattern is still correct —
but the spec teaches the wrong mental model for future callers.
**Proposed fix:** Revise §4.1 to read: "`request()` does not currently
require transient activation per spec, but we preserve the user-gesture
synchronous path because (a) the NoSleep fallback calls
`<video>.play()`, which *does* require transient activation, and (b)
issue w3c/screen-wake-lock#350 may add a transient-activation
requirement in a future spec revision." Same structure in §10.
**Sources:** https://www.w3.org/TR/screen-wake-lock/#the-request-method,
https://github.com/w3c/screen-wake-lock/issues/350

### F1.4 — `'wakeLock' in navigator` is not reliably false on non-Secure-Context origins
**Severity:** NICE-TO-HAVE
**Claim in spec:** §4.1 "`navigator.wakeLock` is undefined on plain
HTTP. Detection is via `'wakeLock' in navigator`, which returns false on
non-Secure-Context origins."
**Reality:** `[SecureContext]` on the IDL does gate exposure in all
current implementations (Chrome, Firefox, Safari), so the property is
indeed absent on http origins in those browsers. That part of the claim
holds. But it's worth calling out that Samsung Internet, in-app WebViews
(Facebook/Instagram/Line browsers), and various Android Chromium forks
have historically been inconsistent about `[SecureContext]`
enforcement. Some expose the attribute but reject at call time with
`NotAllowedError`. The existing `try/catch` in §4.3 already handles this
correctly, so no code change needed — but the claim in §4.1 is worded
more absolutely than the real-world landscape justifies.
**Impact:** Low. Code handles the edge correctly via the catch.
**Proposed fix:** Soften §4.1 wording from "returns false on
non-Secure-Context origins" to "returns false on non-Secure-Context
origins in all spec-conforming browsers; some non-conforming WebViews
expose the property but reject the call, handled by the try/catch
below."

### F1.5 — `speechSynthesis` deferral under tab-hide is worse than §OS4 implies; wake-lock does not help when Chrome freezes the tab
**Severity:** NICE-TO-HAVE (OS4 is already deferred, so borderline)
**Claim in spec:** §OS4 "utterances queued while the tab is hidden may
be dropped or delayed by some browsers. Wake-lock minimizes tab-hide
scenarios but does not prevent them."
**Reality:** Chrome 77+ on Android *freezes* backgrounded tabs after
5 minutes, at which point `visibilitychange` no longer fires (a `resume`
event fires on un-freeze instead). SpeechSynthesis queued after a freeze
is dropped silently. Chrome 130 has separately destabilized
`speechSynthesis.speak()` in general, per active Chrome Enterprise
threads. A held screen wake lock does *not* prevent tab-freezing — it
prevents screen-off, which is a different lifecycle. If the user
switches to another app (Maps, phone, messages) during nav, the tab
hides, the wake-lock releases, and after 5 min the tab freezes even
though our code expects `visibilitychange` to fire on return. No TTS
queued during that window will speak.
**Impact:** Low for this spec (OS4 is deferred). But the spec's framing
"wake-lock minimizes tab-hide" is misleading — wake-lock is orthogonal
to tab-hide; it only prevents screen-off. A driver who switches to the
phone app is equally exposed with or without wake-lock.
**Proposed fix:** Clarify §OS4: "Wake-lock prevents screen-off, not
app-switch / tab-hide. TTS survival across app-switch is a separate
concern, tracked elsewhere, and is not materially improved by this
spec." Also add to §5.8 that after Chrome's 5-min freeze, the
`visibilitychange` listener may fire late or not at all, and a
`resume`-event re-acquire path may be needed in a future revision.
**Sources:** https://support.google.com/chrome/a/thread/303329396,
https://github.com/mixmaxhq/meteor-smart-disconnect/issues/11

### F1.6 — Permission-prompt race with `visibilitychange` is unhandled but not currently exploitable
**Severity:** CORRECT-WITH-CAVEAT (documenting for completeness)
**Claim in spec:** §5.8 describes the hide→show cycle; §5.7 describes
the acquire-release race.
**Reality:** No current browser shows a permission prompt for
`wakeLock.request('screen')` — it's auto-granted in Chrome, Firefox, and
Safari when the document is visible. So the "modal browser dialog fires
`visibilitychange`" attack mentioned in the assignment does not apply
today. If a future browser adds a prompt, the `await request` inside
`acquire()` could resolve concurrently with a `visibilitychange`
(visibility → hidden if the prompt steals focus), and the spec's
`shouldBeActive` re-check in §4.3 handles that correctly. I verified
the race logic is sound.
**Impact:** None today. Future-proof.
**Proposed fix:** None. Leave §5.7 as-is.

### F1.7 — `await` across `navigator.wakeLock.request()` is safe; spec's caution is good but rationale is imprecise
**Severity:** CORRECT
**Claim in spec:** §4.3 code comment "no await between shouldBeActive =
true and the request call, so the user-gesture grace window is
preserved."
**Reality:** As discussed in F1.3, Wake Lock doesn't currently require
transient activation — the await is not spec-dangerous. Once inside the
`await navigator.wakeLock.request('screen')`, the promise resolves on a
microtask (V8 implementation) after the browser's platform-level lock
attempt; no user-gesture state is consulted. For NoSleep's `<video>.play()`
inside `enable()`, the gesture must be live at the point of the `.play()`
call — and since `enable()` is invoked synchronously inside our `acquire()`
(no await between the click and `noSleep.enable()`), we're safe.

The §4.3 caution is *operationally* correct (keep the path synchronous)
even though the stated reason (Wake Lock API requires transient activation)
isn't currently true. Don't remove the caution; fix the rationale per
F1.3.
**Impact:** None functionally; teaches the wrong mental model (covered
in F1.3).
**Proposed fix:** Cross-reference F1.3.

### F1.8 — NoSleep.js v0.12.0 is actually from Dec 2020, not May 2022; spec's Appendix A timeline is wrong
**Severity:** NICE-TO-HAVE
**Claim in spec:** Appendix A "v0.12.0 (May 2022) is the current stable
release."
**Reality:** GitHub shows v0.12.0 was released on **December 16, 2020**.
No release has shipped since. The project is effectively unmaintained
(49 open issues, no release in 5+ years). Appendix A's claim that
"The last update added iOS 15 compatibility" is plausible but can't
refer to a May 2022 release that doesn't exist.
**Impact:** Minor fact error, but it's in the portion of the spec that
justifies choosing this library. A 5-year-old unmaintained dependency
is a different risk profile than a 4-year-old recently-updated one.
**Proposed fix:** Correct Appendix A: v0.12.0 is Dec 2020, project is in
deep maintenance mode (no releases in 5 years), accept the risk or
consider the `zakj/no-sleep` fork (TypeScript rewrite, still actively
maintained — search surfaced it in the NoSleep.js alternatives list).
If we go with NoSleep.js v0.12.0 anyway, acknowledge the staleness
explicitly.
**Sources:** https://github.com/richtr/NoSleep.js/releases,
https://github.com/zakj/no-sleep

## Summary

Eight findings total. One MUST-FIX (F1.1) that invalidates the core
"primary vs fallback" architecture — NoSleep.js already calls the Wake
Lock API as its own primary path, so the spec's fallback is not a
fallback on Secure Context where the primary rejects. One SHOULD-FIX
(F1.2) for iOS PWA standalone-mode silent failure. The rest are
documentation / mental-model corrections that don't require code
changes but do require spec-text revisions.

Spec §5.7 race handling is actually *correct*, including the
release-during-pending-acquire logic. That part stands up to attack.
