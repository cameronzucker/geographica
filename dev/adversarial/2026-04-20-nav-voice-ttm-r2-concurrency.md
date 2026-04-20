---
round: 2
angle: Concurrency, timing, and reroute interleaving
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-20
agent: alder
---

# Nav Voice TTM — Round 2 Adversarial Review: Concurrency, Timing, Reroute Interleaving

Spec under review: [docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md](../../docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md)

Cross-checked against:
- `frontend/navigation.js` — checkVoice L357-411, tick L549-651, triggerReroute L654-682, applyReroute L828-851, deadReckonTick L686-700, stale-checker L706-715, updateGPS L802-821, reset L726-750
- `frontend/nav-ui.js` — onReroute L508-539, attemptReroute L541-590 (retry + abort semantics)
- Reference R2 pattern: [dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md](2026-04-21-nav-voice-picker-r2-concurrency.md) — async-delivery mock requirements

JS is single-threaded but the engine interleaves with (a) `setInterval` stale-checker ticks, (b) `setTimeout` reroute-timeout handlers, (c) microtask-delivered `fetch` responses from `attemptReroute`, (d) user event handlers (mute toggle, stop). All races below are sequential-ordering bugs, not literal concurrency — they manifest when state is consulted mid-transition between cooperating handlers.

---

### F2.1 — Reroute timeout fires AFTER successful `applyReroute`, clobbering fresh state

**Severity:** MUST-FIX

**Claim in spec:** §4.5 shows `applyReroute` clears `rerouteTimeoutId` at entry: `if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }`. §4 does not address what happens if the timeout fires *concurrently* with (i.e., microtask-adjacent to) the fetch-settled path.

**Race scenario:** Examining navigation.js L660-669, the `setTimeout(…, REROUTE_TIMEOUT=10000)` handler is:

```js
rerouteTimeoutId = setTimeout(function () {
  rerouteTimeoutId = null;
  if (state === "rerouting") {
    state = "navigating";
    offRouteHistory = [];
    inOffRouteState = false;
    lastRerouteTime = 0;
  }
}, REROUTE_TIMEOUT);
```

1. t=0: user goes off-route. `triggerReroute` sets `state="rerouting"`, `rerouteSeq=1`, schedules `rerouteTimeoutId` for t=10000.
2. t=9995ms: reroute fetch resolves. Microtask from `.then()` in `attemptReroute` runs (nav-ui.js L552-573). `buildRouteData` executes. `nav.applyReroute(newRoute, 1)` is called synchronously from within that microtask.
3. `applyReroute` at L830 checks `seq !== rerouteSeq` → 1 === 1, proceeds. At L831 it calls `clearTimeout(rerouteTimeoutId)`. BUT `clearTimeout` on a timer whose callback has **already been dispatched to the task queue** but not yet executed is a no-op. Node/browser spec: if the task is already on the queue (which can happen if the `setTimeout` fired and its task is queued ~1ms before the microtask that ran the reroute), clearTimeout does nothing.
4. `applyReroute` proceeds: resets `announcedSet = {}`, `speedSamples = []` (per §4.5), sets `state="navigating"`, calls `tick(lastGPS)`.
5. `tick()` runs against the *new* route. Far-tier may fire for maneuver 0 of the new route. Entry added to `announcedSet["1-far"]`.
6. The stale timeout callback now executes. It sees `state === "navigating"` (no longer "rerouting") at L662 — so the `if` guard protects state/offRouteHistory/inOffRouteState/lastRerouteTime. **But** `rerouteTimeoutId = null` fires unconditionally at L661. This is benign for the current code path, but:
7. **The TTM spec adds no mitigations for this timer, and the timeout guard is not defensive enough for the next class of race:** if the applyReroute happens to fire *exactly* when `state==="rerouting"` still holds (e.g., a second-reroute scenario where the caller `triggerReroute`'s again, setting state back to "rerouting" before the stale timeout's task runs), the stale timeout wipes the second reroute's `offRouteHistory`/`inOffRouteState`/`lastRerouteTime` — masking the legitimate reroute.

**Impact:** In the plain case — benign. In the reroute-during-reroute case (which IS possible because `applyReroute` doesn't nullify `rerouteSeq` tracking of the pending timer from the PRIOR reroute that this one is replacing) — the prior reroute's timeout can fire during the current reroute's "rerouting" state window and silently reset its fields.

**Proposed fix:** In `applyReroute`, do not rely on `clearTimeout`'s idempotence against already-dispatched tasks. Bump `rerouteSeq` on successful apply so any in-flight stale-timeout callback can range-check (`if (myCapturedSeq !== rerouteSeq) return;`) — mirror the seq-capture pattern the spec inherits from L679/L828. The timeout closure should capture `rerouteSeq` at scheduling time:

```js
var mySeq = rerouteSeq;
rerouteTimeoutId = setTimeout(function () {
  rerouteTimeoutId = null;
  if (mySeq !== rerouteSeq) return;  // applyReroute or a newer triggerReroute superseded us
  if (state === "rerouting") { ... }
}, REROUTE_TIMEOUT);
```

**Test to add:** `test_reroute_timeout_superseded_by_apply`: synthesize a reroute, fake-advance time to 9999ms, fire a fake `applyReroute`, then advance the remaining 1ms to allow the timeout's already-queued task to run. Assert `announcedSet`/`offRouteHistory`/`inOffRouteState` still reflect the applied route, not the stale timeout's reset.

---

### F2.2 — Stale-reroute-drop silently skips speedSamples reset, breaking G6 invariant

**Severity:** MUST-FIX

**Claim in spec:** §G6: "Reroute clears all voice state: `announcedSet` AND the speed-sample window. The new route's first prompt fires without suppression from prior state." §4.5 puts the `speedSamples = [];` line inside `applyReroute`, **after** the stale-seq check.

**Race scenario:** Examining navigation.js L828-830:

```js
applyReroute: function (routeData, seq) {
  if (seq !== rerouteSeq) return;   // ← drop on stale
  ...
  announcedSet = {};
  speedSamples = [];  // per §4.5
```

1. t=0: User goes off-route at intersection A. `triggerReroute(lat1, lng1)` → `rerouteSeq=1`. Fetch kicks off.
2. t=8s: GPS update. User has kept driving off-route; snap still off. `triggerReroute` is NOT called again because `lastRerouteTime` is still within `REROUTE_COOLDOWN=15000`.
3. t=10.01s: fetch resolves. `applyReroute(newRoute1, seq=1)`. Passes. `announcedSet = {}`, `speedSamples = []`, `tick(lastGPS)` runs.
4. BUT scenario variant — heavy off-route, user completely past A: t=3s fetch A times out (REROUTE_TIMEOUT fires, state reverts to "navigating", `lastRerouteTime=0`). t=3.5s next tick detects off-route again: `triggerReroute(lat2, lng2)` → `rerouteSeq=2`.
5. t=5s: Fetch from reroute 1 (which was **not aborted** — look at nav-ui.js L542, `rerouteAbortController.abort()` is called on EACH `attemptReroute` invocation, which cancels prior fetches; good for nav-ui side, but navigation.js has no idea). `rerouteAbortController` *does* abort the prior reroute's fetch per nav-ui.js L542 — so the stale-drop path in the engine isn't triggered for this specific scenario.
6. **Revised race:** retry semantics (nav-ui.js L578-584) reuse `seq` across exponential-backoff retries. If retry #2 of reroute A resolves, but in the meantime `triggerReroute` was called a second time (reroute A timeout fired at t=10s, reroute B scheduled at t=10.1s bumping `rerouteSeq=2`), retry #2 of A still carries `seq=1`. It calls `applyReroute(newRouteA, 1)`. L830 drops it (`1 !== 2`). **But** `speedSamples` should be reset for the ACTUAL applied reroute B — which will happen when B's response arrives. Fine in the happy path.
7. **The real bug:** what if reroute A's retry #3 resolves after reroute B's `applyReroute` already ran? B's `speedSamples` reset was fine at its apply-time. Then A's retry resolves 2s later with `seq=1`. Engine drops it (correct). But imagine `speedSamples` has now repopulated with 3 samples from B's route. Nothing's wrong here either.
8. **The asymmetry:** the spec's §G6 invariant is "reroute clears speedSamples." This invariant is **defined against successful applyReroute**, not against *reroute events*. Readers — including future maintainers and the subagent executing the plan — will read §G6 and assume every reroute trigger clears speedSamples. It does not. Under timeout-then-retry, a reroute can trigger and never clear (because the retry was superseded).

**Impact:** The spec says one thing (§G6 "reroute clears…") and the code does another (only `applyReroute` success clears). If a reviewer later asks "I trust §G6; why is speedSamples populated across this reroute?" — the answer is "the reroute timed out and was dropped." Not wrong, but under-documented. Worse: the spec's test for §6.3 says "Drive an approach that fires one near-tier for maneuver 0. Invoke `applyReroute(newRoute, seq)`. Assert `_getSpeedSamples()` is empty." This test will pass even if the stale-drop bug masks the reset — it tests the success path only.

**Proposed fix:** Clarify §4.5 and §G6 to state: "When a reroute **successfully applies** (not just triggers), speedSamples and announcedSet are cleared. A reroute request that times out or is superseded leaves state on the *previous* route untouched — which is the desired behavior since we continue navigating the previous route." Add a test to §6.3 for the stale-drop case: fire `applyReroute(route, wrongSeq)`, assert speedSamples is unchanged.

Optionally: call `speedSamples = []` alongside the `lastRerouteTime=0` reset in the timeout handler at L663-668, for symmetry.

---

### F2.3 — `deadReckonTick` + next real GPS tick can fire the same tier twice in different execution contexts

**Severity:** SHOULD-FIX

**Claim in spec:** §E7 states: "`deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap. `lastSpeed` from the last real GPS tick is used by DR's extrapolation but `speedMedian()` reads `speedSamples` — these do not update during DR. TTM during DR uses the last-real-median."

**Race scenario:** Examining navigation.js L686-700 and L706-715:

- Stale-checker interval: every 1000ms, checks `Date.now() - lastGPSTime >= GPS_STALE_TIMEOUT (3000)`. If stale, calls `deadReckonTick()`.
- `deadReckonTick` calls `checkVoice(drSnap)` using the DR'd snap position.
- `checkVoice` reads `speedMedian()` from current `speedSamples` — which is NOT cleared on GPS outage. So it uses the last-known real speeds.

Sequence:
1. t=0: Real GPS at 10m/s, distance to maneuver 1 = 40m. `speedSamples=[10,10,10]`. ttm=4s. Near-tier condition met: `announcedSet["1-near"]=true`, `announcedSet["1-far"]=true` (D1). Prompt fires.
2. t=1s: GPS stops arriving (tunnel). Real ticks pause.
3. t=4s: Stale-checker fires (≥3s). `deadReckonTick()` runs. DR extrapolates: user has moved 30m in 3s at lastSpeed=10m/s. New drSnap has distance to maneuver 1 ≈ 10m (or past it, depending on geometry). `checkVoice(drSnap)` runs — but maneuver 1 is already marked in `announcedSet`, so it's a no-op. Good.
4. t=5s: Real GPS comes back. `updateGPS` fires. `tick()` runs on the new real snap. But depending on how far the user actually moved during outage, `currentManeuverIdx` may have advanced past maneuver 1 to maneuver 2.
5. L573: `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`. If this now equals 2 (user passed maneuver 1 during outage), `checkVoice` computes `nextIdx=3`, looks at maneuver 3. No conflict.
6. **But** what if the DR'd snap in step 3 was already at maneuver 2's segment (user crossed during outage)? `deadReckonTick` L697: `currentManeuverIdx = findManeuverForSegment(drSnap.segmentIndex)`. Now `currentManeuverIdx=2`. `checkVoice` for maneuver 3 runs. If it's close enough, fires a prompt. User hears "turn right onto Elm" during GPS outage. Fine.
7. t=5s real GPS: `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)` — may still be 2 (user is between maneuver 2 and 3). `checkVoice` sees `announcedSet["3-near"]=true` from DR → no-op. Good — but only because D1 marked both keys during DR.
8. **Actual race:** what if DR'd in step 3 fired ONLY a far-tier (ttm = 15s at slower speed; D1 suppression doesn't trigger since `!nearWouldFire`)? `announcedSet["3-far"]=true` only. t=5s real GPS: real speed is now 15m/s (user sped up post-tunnel). Real snap has distance=100m to maneuver 3; real ttm = 100/15 = 6.7s. Near-tier fires (6.7 ≤ near_s=3? no; 6.7 > 3; so far-tier would fire but already did). Wait — re-check the math: at 15m/s, 100m is 6.7s — neither near (≤3s) nor the far threshold (which we already fired), so nothing fires. OK.

Let me construct the actual adversarial case: 
- t=0: speedSamples=[5,5,5]. ttm at 90m = 18s, far fires, marked 3-far.
- t=1s: GPS outage.
- t=4s: stale-checker, `deadReckonTick`. DR'd snap has distance=75m. speedMedian still 5 (§E7). ttm=15s. `farWouldFire` at 75m? Already announced, no. `nearWouldFire`? 15 ≤ 3? No. 75m ≤ 50m floor? No. Nothing fires. OK.
- t=5s: real GPS after outage shows speed jumped to 30m/s (user accelerated to highway speed). `pushSpeedSample(30)` → speedSamples=[5,5,30]. Median=5. Distance now 60m. ttm=12s. Nothing new fires. OK.
- t=6s: speedSamples=[5,30,30]. Median=30. Distance=30m. ttm=1s. Near fires. Expected behavior.

This mostly works, but there's an edge: **the `currentManeuverIdx` mutation in `deadReckonTick` at L697 is made against a DR'd position, which can be WRONG if GPS comes back showing user was actually OFF the route (took an off-ramp during outage).** Real GPS then triggers off-route detection and reroute — but `currentManeuverIdx` has already advanced under DR. If the real-GPS tick detects off-route at L620-641, `triggerReroute` fires. Then `applyReroute` resets `currentManeuverIdx=0`. Good — covered.

**The actual latent bug:** `deadReckonTick` calls `checkVoice` with `drSnap`, which mutates `announcedSet` using `nextIdx = currentManeuverIdx + 1` where `currentManeuverIdx` was just set by DR. If GPS comes back and REAL `currentManeuverIdx` is LESS than DR's (e.g., DR over-estimated distance traveled), then `checkVoice` under real GPS looks at a DIFFERENT `nextIdx` than DR did. DR marked `announcedSet["3-far"]`; real GPS checks `announcedSet["2-far"]` (still false), fires maneuver 2's prompt, even though we already voiced maneuver 2 as part of the DR sequence. Double-announcement.

Constructing this concretely:
- Route maneuvers at coord indices 10 (maneuver 1), 20 (maneuver 2), 30 (maneuver 3).
- t=0: real snap segmentIndex=8, currentManeuverIdx=0. Fire far for maneuver 1.
- t=1s: GPS outage.
- t=4s: `deadReckonTick`. lastSpeed was high (say 20m/s from pre-outage). DR extrapolates 3s × 20m/s = 60m. drSnap.segmentIndex now =22. `currentManeuverIdx = findManeuverForSegment(22) = 2` (between maneuver 2 at 20 and maneuver 3 at 30). `checkVoice` fires maneuver 3's far (nextIdx=3). Maneuver 2's "far" was skipped entirely (we jumped from checking maneuver 1 to checking maneuver 3 with no tick at maneuver-2-eligible position). `announcedSet = {"1-far": true, "3-far": true}`. Note: "2-far" and "2-near" are false.
- t=5s: real GPS shows user is at segmentIndex=15, currentManeuverIdx=1 (DR over-estimated). `checkVoice` with nextIdx=2. `announcedSet["2-far"]` false. Fires prompt for maneuver 2. Valid — user really did need that prompt (they're still approaching maneuver 2). But the DR prompt for maneuver 3 was **premature** — user was not actually past maneuver 2.

**Impact:** (a) During GPS outage, DR'd prompts can fire for maneuvers the user has NOT actually reached; `announcedSet` now locks them out even if the user eventually arrives there. (b) If DR's `currentManeuverIdx` advances too fast (past the true position), maneuvers are **skipped entirely** in announcement state — the user will NEVER hear "turn left onto Oak" because `checkVoice` hops from maneuver 1 to maneuver 3 without visiting maneuver 2's far-tier threshold.

**Proposed fix:** `deadReckonTick` should NOT call `checkVoice`. Voice prompts during GPS outage are low-value (driver can't see the map update either — screen may be frozen) and the risk of wrongly marking `announcedSet` for not-yet-reached maneuvers is a regression. Alternative: DR runs `checkVoice` but uses a *tentative* announcedSet that merges back only if real GPS confirms the position advancement.

**Test to add:** `test_dr_does_not_mark_unreached_maneuvers`: route with 3 maneuvers. Fire normal tick at pre-m1 position. Stop GPS. Fast-forward 10s. Assert after real-GPS-resumes (at post-m1, pre-m2 position), maneuver 2's far-tier still fires. If DR pre-marked "2-far", this test will fail — which is the bug detection we want.

---

### F2.4 — `rerouteSeq` captured in closure at `triggerReroute` call site vs mutated later

**Severity:** SHOULD-FIX

**Claim in spec:** None — the spec does not touch `triggerReroute` or `rerouteSeq` semantics (§NG4 "Changes to the reroute trigger logic… out of scope"). But TTM's `speedSamples` reset is *coupled* to `applyReroute` success, and `applyReroute`'s stale-seq drop (L830) is the gating condition.

**Race scenario:** Examining navigation.js L659 and L679:

```js
rerouteSeq++;
rerouteTimeoutId = setTimeout(function () { ... }, REROUTE_TIMEOUT);
if (onRerouteCb) {
  onRerouteCb({
    ...
    _seq: rerouteSeq  // captured at call time
  });
}
```

The `_seq` payload is a *primitive number*, captured at the moment `onRerouteCb` is invoked. `nav-ui.js` stashes it as `seq = info._seq` (L535). Later `nav.applyReroute(newRouteData, seq)` at L570 passes it back.

Between the `triggerReroute` invocation and the `applyReroute` callback, `rerouteSeq` may be incremented by another `triggerReroute` call (if the engine re-entered rerouting). The stale-drop at L830 handles this: `if (seq !== rerouteSeq) return;` — drops the old reroute.

**But** the retry logic in nav-ui.js L578-584 reuses the captured `seq` across retries:

```js
rerouteRetries++;
if (rerouteRetries <= MAX_REROUTE_RETRIES) {
  var delay = Math.pow(2, rerouteRetries) * 1000; // 2s, 4s, 8s
  var timeoutId = setTimeout(function () {
    attemptReroute(body, seq, info);  // ← reuses original seq
  }, delay);
  ...
}
```

**Scenario:**
1. t=0: Reroute 1. `rerouteSeq=1`. Fetch fails (network blip).
2. t=2s: Retry 1 scheduled.
3. t=4s: Meanwhile, engine detects off-route AGAIN (user drove past the failed reroute point). `triggerReroute` called. `rerouteSeq=2`. Fetch B kicks off. `state` is already "rerouting" (L658 resets it; L656 gates on `lastRerouteTime` — within `REROUTE_COOLDOWN=15s`, so `triggerReroute` EARLY-RETURNS).
4. Wait — `triggerReroute` L656: `if (now - lastRerouteTime < REROUTE_COOLDOWN) return;`. `lastRerouteTime` was set at t=0. t=4s is still within 15s cooldown. So `triggerReroute` bails. `rerouteSeq` stays at 1. Good.
5. BUT: the REROUTE_TIMEOUT (10s) at t=10s fires, sees `state === "rerouting"` still, resets `state="navigating"`, `lastRerouteTime=0`. Now cooldown is cleared.
6. t=10.5s: user is still off-route. `triggerReroute` succeeds (cooldown clear). `rerouteSeq=2`. Fetch B kicks off.
7. t=11s: retry #2 of reroute 1 resolves (it had a fetch in flight, remember — the `attemptReroute` retry chain stores seq=1 and attempts again at t=6s [2s backoff from t=4s failure]; this resolves at t=11s with a successful trip). `applyReroute(newRouteA, 1)`. L830: `1 !== 2` → drops.

Stale-drop works correctly here. But:

8. t=10.5s fetch B from reroute 2 resolves. `applyReroute(newRouteB, 2)`. Passes. New route applied. 

**The real race:** What if at t=11s, reroute A's retry #2 resolved FIRST (before fetch B), THEN fetch B settles second? Let's re-order:
- t=10s: TIMEOUT fires, state→"navigating", `lastRerouteTime=0`.
- t=10.5s: off-route detected. `triggerReroute` starts fetch B. `rerouteSeq=2`. `state="rerouting"`.
- t=10.6s: retry #2 of A resolves (slightly before B). `applyReroute(routeA, 1)`. `1 !== 2` → drops. Good.
- But **the attemptReroute function at nav-ui.js L542 ALWAYS calls `rerouteAbortController.abort()` on each invocation**. So when the retry at t=6s was scheduled, the retry-delay timer fires at t=6s and calls `attemptReroute(body, seq=1, info)`, which aborts any prior in-flight fetch. Then at t=10.5s, `attemptReroute(bodyB, seq=2, infoB)` is invoked — this ABORTS the retry-in-flight fetch from reroute A (the one started at t=6s)! So A can never resolve after B starts, because `rerouteAbortController` is a **module-singleton** at nav-ui.js.

Confirmed: the singleton `rerouteAbortController` means at most one fetch is in flight at any time. So the race in step 7-8 above doesn't actually trigger.

**But the retry backoff timer at L581 is not tied to the abort controller:** if retry #2 of A is scheduled for t=10s and B starts at t=10.5s, the retry-attempt at t=10s would have *already kicked off its fetch* (not yet resolved) when B's triggerReroute at t=10.5s runs `attemptReroute(bodyB, 2, infoB)`. B's attemptReroute aborts the retry-A fetch. Good.

**The latent remaining race:** `rerouteRetries` is a module-singleton counter at nav-ui.js. When B starts at t=10.5s, nav-ui.js L537 resets `rerouteRetries = 0`. But what if A's pending-retry `setTimeout` at t=10s fires between the fetch-B-kickoff and its abort? That timer would call `attemptReroute(bodyA, 1, infoA)` — NOT knowing that B superseded it. This would (a) abort B's fetch, (b) start a new A-fetch. A-fetch resolves. `applyReroute(routeA, 1)`. `rerouteSeq` is now 2 (B bumped it). `1 !== 2`. Dropped.

And B's fetch never completes (got aborted by the spurious A retry). `rerouteRetries` at nav-ui.js was reset to 0 at B's start; now re-increments from A's catch handler (since the A retry's fetch completed OK so no catch; or maybe it errored via `signal.aborted`). The user is stuck with no reroute.

**Impact:** TTM doesn't regress this directly, but the spec's §G6 "reroute clears all voice state" **relies on applyReroute firing**, and the reroute-vs-retry-vs-superseded orchestration is fragile enough that legitimate reroutes can be dropped. The spec should flag this as an out-of-scope concern explicitly AND ensure §6.3 tests cover the "reroute never applies" case: after a triggered-but-unsuccessful reroute, `speedSamples` should retain its pre-reroute contents (i.e., G6 does NOT fire until applyReroute fires).

**Proposed fix:** Spec addition to §7 edge cases: "E10. Reroute triggered but never applied. `triggerReroute` fires; either the fetch times out, or the retry chain exhausts, or a later `triggerReroute` supersedes the seq. In all cases, the engine remains on the OLD route. `speedSamples` and `announcedSet` are NOT cleared — G6 invariant gates on `applyReroute` success, not on reroute trigger. This is correct because the user is still navigating the old route; stale state against the old route is the right state."

**Test to add:** `test_reroute_trigger_without_apply_preserves_speed_samples`: drive to accumulate 3 speedSamples. Trigger off-route detection. Assert onReroute fires. Then fire `applyReroute` with `seq=999` (wrong seq; simulating supersede). Assert speedSamples is unchanged from pre-trigger state.

---

### F2.5 — Mute toggle mid-checkVoice: single-threaded guarantee holds, but read-after-compute pattern documents poorly

**Severity:** NICE-TO-HAVE

**Claim in spec:** §I8: "`muted = true` prevents `onVoiceCb` invocation but does NOT prevent `announcedSet` population." §4.3 checkVoice code shows:

```js
announcedSet[nearKey] = true;
announcedSet[farKey] = true;  // D1 suppression
if (!muted && onVoiceCb) onVoiceCb(text);
```

**Race scenario:** `setMuted(val)` at L854-856 is a naked assignment with no guards. Single-threaded JS means the `if (!muted …)` check at L209 cannot race against `muted = !!val` *mid-check* — but the interaction with the next tick DOES matter.

1. t=0: tick() runs. `checkVoice` computes `nearWouldFire=true`. Sets `announcedSet[nearKey]=true, announcedSet[farKey]=true`. Reads `muted=false`. Calls `onVoiceCb(text)`.
2. User clicks mute button WHILE onVoiceCb is executing (e.g., onVoiceCb kicks off `speechSynthesis.speak(u)` which is synchronous-enqueue; then muted flips during the same tick). The flip can happen via `button.onclick` handler — but that handler runs on the NEXT event-loop iteration, not during the current synchronous call chain. So this is safe.
3. **BUT** in §E8: "onVoiceCb("") because we did not add a guard — acceptable." What if `onVoiceCb` triggers a UI update (e.g., nav-ui.js displays "last voice prompt: …" textually) which calls `setMuted(true)` as a side effect? Unlikely but possible via an observer pattern. In this case the current tick's onVoiceCb has already run so the mute-state flip doesn't affect it, but the NEXT tick will see muted=true and skip voicing. But `announcedSet` for this maneuver is already populated from the first tick. If the user un-mutes later, the prompt does not replay. Correct per §I8.
4. **The actual concern** (from the task prompt): the spec's G9 says "Mute-state interaction unchanged." But the mute check moved from `announce()` (which was the old code path) to inlined within `checkVoice` (§4.3). The old `announce()` was at L343-351 and gated ALL announcements through one mute check. The new inlined check gates per-branch (one check at L209 in the near-branch, one at L215 in the far-branch). If a future refactor adds a third branch (e.g., a §NG1-deferred highway-exit tier) and forgets the mute check, the mute-state guarantee silently breaks.

**Impact:** The mute check is now scattered across §4.3's branches. A future edit that adds a branch without the mute guard would ship a mute-is-ignored bug.

**Proposed fix:** Extract the onVoiceCb call into a local helper within the IIFE:

```js
function emitVoice(text) {
  if (!muted && onVoiceCb) onVoiceCb(text);
}
```

Use it everywhere in `checkVoice`. Documents the invariant structurally. Zero runtime cost.

**Test to add:** `test_mute_toggle_mid_tick_does_not_replay`: mute at t=0 BEFORE a tick that would fire near-tier. Run tick. Assert onVoiceCb was NOT called. Assert `announcedSet[nearKey]=true` still populated. Un-mute. Run another tick (still in near-tier range). Assert onVoiceCb still NOT called (lock held by announcedSet, not by muted).

---

### F2.6 — `lastGPSTime` refresh on unchanged-position suppresses DR but also freezes speedSamples

**Severity:** SHOULD-FIX

**Claim in spec:** §4.2: "Integration into `tick()`: immediately after the existing line `lastSpeed = gpsSpeed;` (around navigation.js:559), add `pushSpeedSample(gpsSpeed);`." §E7 addresses DR-speed-sample interaction. The spec does NOT address the `updateGPS` dedup path at L811-820.

**Race scenario:** Examining L811-820 closely:

```js
var positionChanged = !lastGPS ||
  lastGPS.latitude !== data.latitude ||
  lastGPS.longitude !== data.longitude;

lastGPS = data;
lastGPSTime = Date.now();

if (state !== "idle" && positionChanged) {
  tick(data);
}
```

1. User stops at a red light at 80m from next maneuver (beyond the 50m floor). speedSamples=[0,0,0] (from the final decelerating ticks). speedMedian=0, clamped to MIN_SPEED_FLOOR=1.0.
2. GPS continues to report position at 1Hz, but coordinates are identical (stationary). `positionChanged=false`. `tick()` is NOT called. But `lastGPSTime` IS refreshed (L816). Good — stale-checker doesn't fire DR.
3. User sits at the light for 45s. During this window: no `tick()` call, so no `pushSpeedSample()`. speedSamples stays at [0,0,0]. Median=0 → clamped to 1.0 → TTM for 80m distance = 80s > 30s far threshold. Nothing fires at the light. Correct per §G3.
4. Light turns green. User accelerates to 15 m/s. First GPS update: position changes. `tick()` fires. `pushSpeedSample(15)` → speedSamples=[0,0,15]. Median=0 (index 1 of sorted [0,0,15] is 0). Clamped → 1.0. TTM for (now) 70m = 70s. Far still doesn't fire. But real TTM at 15m/s is 4.7s — should near-fire imminently.
5. Next tick: speedSamples=[0,15,15]. Median=15. TTM for 60m = 4s. Near-tier condition: 4s ≤ near_s=3? No. 60m ≤ 50m floor? No. Near does NOT fire. Far condition: 4s ≤ 30s. Yes. Far fires. User hears "In 60 meters, turn left." Reasonable.
6. Next tick: speedSamples=[15,15,15]. Median=15. Distance=45m. TTM=3s. Near-tier ≤ 3? Yes → near fires. User hears "Turn left onto Mulberry." Good.

So the behavior is: at light stop, the far-tier is NOT fired (TTM=80s >> 30s threshold, even though the driver has a minute of "advance notice" from being stopped). When they start moving, the far-tier fires at typical distances. This matches user expectations and §G3/§E5.

But there's a subtle failure: **during the red light wait, speedSamples ages past its natural window** (the last 3 samples were 45+ seconds ago — not "recent" speeds at all). This doesn't matter for THIS scenario but does matter for:

**Scenario B:**
1. User driving at 10 m/s, 300m from maneuver 1. speedSamples=[10,10,10].
2. User stops at light at 200m. Decelerates over 5 ticks; speedSamples becomes [0,0,0] after several stationary ticks.
3. Red light holds 60s. speedSamples stays [0,0,0] (no ticks because `positionChanged=false`).
4. Light turns green; user accelerates very quickly (sports car, empty intersection) to 30 m/s by the 200m mark — crossing the far-tier threshold within 2 ticks.
5. Tick 1 post-light: speed=20m/s. speedSamples=[0,0,20]. Median=0→1.0. Distance=195m. TTM=195s. Nothing fires.
6. Tick 2: speed=30m/s. speedSamples=[0,20,30]. Median=20. Distance=170m. TTM=8.5s. Near-tier? No. Far tier? Yes. Fires.
7. Tick 3: speed=30m/s. speedSamples=[20,30,30]. Median=30. Distance=140m. TTM=4.7s. Already far-fired. Near? 4.7 ≤ 3? No. Nothing fires.
8. Tick 4: Distance=110m. Speed=30m/s. TTM=3.7s. Still not near.
9. Tick 5: Distance=80m. TTM=2.7s. Near fires.

So both tiers fire but far fires LATE (at 170m instead of the "ideal" ~300m at steady 10m/s which would have been ttm=30s) because speedSamples were aged at 0 from the light.

**Impact:** After a long red-light wait, the first maneuver approached from the light has a *delayed far-tier* announcement because speedSamples is still populated with zeros. Not terrible — far still fires before near. But violates the spirit of "30 seconds of advance notice" at cruising speed.

**Proposed fix:** (a) Drain speedSamples when GPS reports the same position for N ticks (say, 5 consecutive dedup'd updates). I.e., if `positionChanged=false`, record it in a counter; after 5 stale updates, clear speedSamples so the next `tick()` starts with fresh data. (b) Simpler: on first `positionChanged=true` after a run of false, shift speedSamples to exclude the stale zeros. (c) Even simpler: don't push `0` to speedSamples when gpsSpeed is 0 AND position didn't change. But this changes the semantics materially and risks missing legitimate "stopped in traffic" signals.

Option (a) is cleanest and matches the "window represents current driving state" intent.

**Test to add:** `test_far_tier_timing_after_long_stop`: run ticks at 10m/s until speedSamples=[10,10,10]. Hold position stationary for 60 simulated seconds (all dedup'd, no ticks). Accelerate back to 30m/s. Assert the FIRST post-stop tick at 300m distance fires far-tier (or the second; but assert it fires before distance drops below 150m).

---

### F2.7 — `currentManeuverIdx` can advance by >1 in a single tick; skipped maneuver's announcements never fire

**Severity:** SHOULD-FIX

**Claim in spec:** §4.3 checkVoice uses `nextIdx = currentManeuverIdx + 1`. Nothing addresses rapid advancement.

**Race scenario:** Examining navigation.js L573: `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`. This is **derived** from the snap; no monotonicity check, no rate limit.

1. Route has 5 maneuvers at segmentIndex=[5, 15, 25, 35, 45].
2. t=0: Real GPS at segmentIndex=14. `currentManeuverIdx=1` (past maneuver 1, approaching 2). `announcedSet["2-far"]=true` fired last tick.
3. t=1s: GPS outage. DR extrapolates OR the next real GPS is 5 seconds late and user was driving at 25m/s — a GPS jump of 125m, covering maybe 30 segments.
4. Real GPS at segmentIndex=33. `currentManeuverIdx=3`. `nextIdx=4`. Maneuver 4 is checked. `announcedSet["4-far"]` may or may not fire.
5. Maneuver 2 and 3 — *skipped entirely from the announcement state machine*. Their far/near keys are never examined. They never fire.

This isn't a bug if the user really did drive past them too fast for any announcement (25m/s through three 10-segment maneuvers = 2 seconds per maneuver, near threshold=3s wouldn't fire anyway). But consider:

**Scenario B:** route cul-de-sac. User briefly drives onto a short segment that's part of maneuver 2's end, then backs out (incorrect GPS glitch showing jump-forward-then-jump-back). Tick 1: segmentIndex=14 (maneuver 1). Tick 2: segmentIndex=26 (maneuver 3 territory due to glitch). Tick 3: segmentIndex=15 (back to maneuver 2). 

- Tick 2: `currentManeuverIdx=3`, `nextIdx=4`. Maneuver 4 checked. Maybe fires "4-far".
- Tick 3: `currentManeuverIdx=2`, `nextIdx=3`. Maneuver 3's "3-far" has never fired. If distance criteria met, it fires. OK.
- But the "4-far" fired prematurely is now locked in. User hears "in 400 meters, turn right" (maneuver 4's prompt) but is actually at maneuver 2. Then later when user *actually* approaches maneuver 4, its announcedSet lock means no repeat — driver gets no prompt at the correct moment.

**Impact:** GPS glitches that jump forward-then-back can prematurely announce distant maneuvers AND lock them from repeating at the correct moment.

**Proposed fix:** In `checkVoice`, only allow announcements for `nextIdx = currentManeuverIdx + 1` if `currentManeuverIdx` advanced by ≤ 1 since the last tick. If advancement jumped >1, log and skip this tick's `checkVoice` (the next tick will catch up). OR: in `findManeuverForSegment`, add monotonicity — never return less than `currentManeuverIdx` (treating the index as sticky-forward). This protects against forward-then-back glitches.

**Test to add:** `test_glitchy_gps_jumps_do_not_lock_future_maneuvers`: feed ticks with `segmentIndex` sequence [10, 30, 15, 35]. Assert that after all ticks, maneuver 3's "3-far" is either unfired (pending) or fired at tick 4 — not pre-locked by the tick 2 jump.

---

### F2.8 — Arrival geofence + near-tier race for final maneuver

**Severity:** SHOULD-FIX

**Claim in spec:** §E5 addresses "stopped at red light within floor" but does not address the final-maneuver-before-arrival case. §7 examines the final maneuver under E5 but the ordering of arrival vs near-tier is not specified.

**Race scenario:** Examining navigation.js L608-617 (arrival check) and L648 (checkVoice):

```js
// tick() lines:
if (distToDest <= ARRIVAL_GEOFENCE && nearEnd) {   // L612 — ARRIVAL_GEOFENCE=30
  state = "arrived";
  ...
  return;
}
...
checkVoice(snap);   // L648
```

Arrival check runs BEFORE checkVoice. If arrival condition (≤30m to destination AND within final ARRIVAL_SEGMENTS=3 segments) is met, `tick()` returns early. `checkVoice` does not run.

1. Final maneuver's begin_shape_index is at, say, the second-to-last coord. Destination is the last coord. Distance between them: 30m.
2. User approaches at 10 m/s. Distance to final maneuver = 100m → 80m → 60m → 40m → 20m.
3. At distance=40m: far already fired earlier. Near-tier check: 40m ≤ 50m floor → near-tier fires. `announcedSet[nearKey]=true`. User hears "Turn left onto Mulberry" (the final maneuver).
4. Continue at 10m/s. Distance to final maneuver = 20m. But distance to destination = 20+30 = 50m (the destination is 30m past the final maneuver). `distToDest=50m > 30m ARRIVAL_GEOFENCE`. No arrival yet.
5. Distance to final maneuver = 0 (at the maneuver). distToDest = 30m. arrival condition met (≤30). state→"arrived". onArrivalCb fires. nav-ui.js L503-506: "You have arrived at your destination" voiced.

This works. The near-tier for final maneuver fired at 40m, THEN arrival fired at destination. Good.

**But Scenario B — the final maneuver's begin_shape_index IS the last coord** (valhalla sometimes emits a "arrive" maneuver at the destination itself, distinct from the final "turn" maneuver):

1. Route has final maneuver (e.g., "Your destination is on the right") at the destination's coord exactly. distance between it and the destination = 0.
2. User approaches. Distance to final maneuver = 40m. 40m ≤ 50m floor → near-tier fires. User hears "Your destination is on the right."
3. User at distance = 30m → distToDest = 30m → ARRIVAL_GEOFENCE triggers. state→"arrived". "You have arrived" voiced.

Two announcements within 10m of each other: "Your destination is on the right" and "You have arrived." Clustered but OK.

**Scenario C — final maneuver's begin_shape_index is AT the destination, and user is approaching at high speed:**

1. User at 30m/s. Distance to destination = 100m. distToDest = 100m, not yet arrived. distance to final maneuver = 100m.
2. Tick at 100m distance. TTM=100/30=3.3s (far tier is [30,3], so 3.3>3 near; 3.3<30 far). Far fires? Far already fired earlier (at ttm=30s → 900m distance). Yes, already fired. Near? 3.3 ≤ 3? No. 100m ≤ 50m floor? No. Nothing.
3. Tick 1s later: distance=70m. TTM=2.3s. Near fires. announcedSet[nearKey]=true. User hears final maneuver prompt. `text` is the final maneuver's verbal_pre_transition.
4. Tick 1s later: distance=40m. distToDest=40m. Still >30. Arrival not yet. checkVoice runs: announcedSet locked, no fire.
5. Tick 1s later: distance=10m. distToDest=10m ≤ 30. **Arrival check fires FIRST** (L612), returns early. checkVoice does NOT run. Fine — final near already fired at step 3.
6. Arrival prompt: "You have arrived."

Good. Now **Scenario D** — user drives at 30m/s and GPS updates at 1Hz. Distance jumps:

1. Tick 0: distance=120m, ttm=4s. Near? 4≤3? No. Far already fired. Nothing.
2. Tick 1s: distance=90m. ttm=3s. Near? 3≤3? YES. Near fires.
3. Tick 2s: distance=60m. already announced. No.
4. Tick 3s: distance=30m. distToDest=30m. ARRIVAL_GEOFENCE triggers. "Arrived" fires.

Good.

**Scenario E** — GPS updates at 1Hz, user at 35m/s:
1. Tick 0: distance=140m. ttm=4s. No fire.
2. Tick 1s: distance=105m. ttm=3s. Near fires.
3. Tick 2s: distance=70m. No fire (already announced).
4. Tick 3s: distance=35m. distToDest=35m. Not yet arrived (≤30 needed). No checkVoice-near (already fired). No arrival.
5. Tick 4s: distance=0m. distToDest=0m. Arrived fires.

Good.

**Scenario F** — user overshoots, backs up (parallel parking style):
1. Approach at 5m/s, all fires normal.
2. User overshoots to distToDest=5m. Arrival fires. state="arrived". `tick()` early-returns forever (state="arrived" → tick L550 returns).
3. User backs up to distToDest=100m (looking for a different parking spot). state still "arrived". No re-fire of anything. User is stuck in the arrived state.

Actually the existing spec tolerates this — arrival is terminal. Not a TTM concern.

**The real latent issue from the task prompt:** the concern is "If arrival is wider than floor." But ARRIVAL_GEOFENCE=30 and floor=50. Floor is WIDER. So near-tier fires before arrival. §7-E5 covers stationary case; non-stationary case above works too.

**But wait:** reread the task prompt's own analysis:

> "If the arrival geofence (30m) is wider than the distance floor (50m) — but 30m is INSIDE the 50m floor, so the floor would have fired near the moment user was at 50m."

This is correct. The near-tier fires at 50m (floor), arrival at 30m. Separate prompts, both fire, 20m apart.

**The actual bug I should flag:** At high speed (30m/s), a single tick can cover 30m. So a tick at 40m-to-final-maneuver transitions in one step to a tick at 10m-to-final-maneuver. That transition *also* crosses `distToDest=30` (arrival geofence). On the FIRST tick in this scenario, distance=40m: near-tier fires (40≤50 floor). distToDest=40m: arrival not yet. On the SECOND tick, distance=10m, distToDest=10m: arrival triggers EARLY RETURN. `checkVoice` is skipped. But near-tier already fired on previous tick.

OK — this works. No bug.

**Where I DO see a concern**: when the final maneuver's begin_shape_index equals the destination's coord index AND floor is 50m, the user hears two voice prompts stacked: final maneuver at floor (50m), arrival at geofence (30m). 20m apart. At 10m/s that's 2 seconds. At 30m/s that's 0.67s — the prompts may overlap in speech engine output, causing one to be cut off. Field-test scenarios may show "Turn left onto Mulberry" being cut off mid-word by "You have arrived."

**Impact:** Audio overlap at high speed on final approach when maneuver coord coincides with destination.

**Proposed fix:** The spec should either (a) document this edge case explicitly and defer it ("prompt overlap on high-speed final approach is an acceptable edge case; real-world driving at 30m/s into a final maneuver that is the destination is rare"), or (b) skip the final maneuver's near-tier announcement when its begin_shape_index is within ARRIVAL_GEOFENCE of the destination — let "You have arrived" carry the moment.

**Test to add:** `test_final_maneuver_at_destination_does_not_stack_prompts`: route with final maneuver at last coord, user approaching at 30m/s. Assert that either (a) the final-maneuver near-tier AND arrival both fire with a clear gap (>2s), OR (b) the final-maneuver near-tier is suppressed when the maneuver coincides with the destination.

---

### F2.9 — `_getSpeedSamples` test hook returns a slice at call time — safe for assertion, hazardous for fake-timer-driven tests

**Severity:** NICE-TO-HAVE (meta-concern about test strategy)

**Claim in spec:** §4.6 defines `_getSpeedSamples: function () { return speedSamples.slice(); }`.

**Race scenario:** §6.2 outlier rejection test synthesizes GPS ticks and calls `_getSpeedSamples()`. The slice copy is safe — tests can't accidentally mutate engine state. But if a test uses fake timers to step time (e.g., `tick()` is simulated at t=1000, tests `_getSpeedSamples()` at t=1500 between ticks), the semantics depend on WHEN the tick's internal state updates happen.

Specifically: in the spec's `tick()` integration (§4.2), `pushSpeedSample` is called "immediately after `lastSpeed = gpsSpeed;`". But `tick()` continues: snap, findManeuver, recordSpeed, off-route checks, arrival check, `checkVoice(snap)`. If a test calls `_getSpeedSamples()` from an earlier hook (e.g., a custom onUpdate callback invoked at `emitUpdate(buildState(snap, false))` at L650 — the FINAL line of tick()), then speedSamples is already fully updated. Good.

**But:** if a test accidentally calls `_getSpeedSamples()` inside a `pushSpeedSample`-triggered callback (there are none today, but future refactor might add "after sample pushed" observer hooks), it could observe a half-updated state (the most-recent sample pushed but other state not yet updated). This is a latent test-reliability concern, not a production bug.

More importantly: **§6.2 outlier rejection test specification is ambiguous** on the timing of `_getSpeedSamples()` calls. The spec says "assert `_getSpeedSamples()` length ≤ SPEED_WINDOW_SIZE." But when? After the outlier tick? After the next tick? Before any tick? The test's success depends on call ordering.

**Impact:** Test flakiness potential in fake-timer tests if hook call timing isn't standardized.

**Proposed fix:** §6.2 should specify: "Call `_getSpeedSamples()` AFTER each synthesized GPS tick completes (i.e., after `updateGPS()` returns). Do not call during a tick's callback invocation."

**Test to add:** Not applicable — this is a test-authoring rule, documented as a code comment at the test hook declaration.

---

### F2.10 — Mock requirements absent: synchronous speechSynthesis mocks will hide all TTM timing bugs

**Severity:** SHOULD-FIX (inherited from voice-picker R2)

**Claim in spec:** §6 tests are described at a behavior level but §6's test infrastructure requirements don't specify mock timing semantics.

**Race scenario:** Unlike the voice-picker spec (which interacts with `speechSynthesis`), TTM's direct runtime dependencies are `Date.now()` and `setTimeout`/`setInterval`. The tests in §6 rely on:
- `simulateApproach({speed, entryDist, costing, steps})` — synthesized GPS ticks at 1Hz.
- Fake-timer helper (§6 mentions `test_runner.mjs` "fake-timer helper if not present").

If the fake-timer infrastructure advances `Date.now()` but does NOT fire `setInterval` callbacks that should have fired during the advancement (specifically the stale-checker at L708-714), then tests that depend on dead-reckoning fallback will silently not invoke DR. Example:

§6.5 "Arrival state + final maneuver near prompt" test (if it existed) would need to NOT have DR misfire during the test. If DR fires correctly in prod but not in test (because fake-timers don't advance intervals), test passes while prod has a race.

**Impact:** Tests pass; prod races. Mirrors F2.12 of voice-picker R2.

**Proposed fix:** §6 must specify: "The fake-timer helper MUST advance `setInterval` callbacks registered via the engine's `startStaleChecker()`. Tests that advance simulated time by ≥1000ms must run any enqueued interval callbacks. Add a meta-test that asserts: after simulated time advancement past 1s, the stale-checker callback has been invoked at least once." Alternatively, the test should override the stale-checker interval with a manually-invoked helper so tests don't depend on interval simulation.

**Test to add:** `test_fake_timers_advance_stale_checker`: set up engine, start nav, sleep-fake 3500ms without sending GPS, assert `deadReckonTick` was invoked (via a spy on `checkVoice` or `_getSpeedSamples`).

---

### F2.11 — `lastGPS = data` mutation before `positionChanged` check creates false dedup on rapid differing data

**Severity:** NICE-TO-HAVE

**Claim in spec:** None — the spec does not touch L811-820.

**Race scenario:** Examining L811-816:

```js
var positionChanged = !lastGPS ||
  lastGPS.latitude !== data.latitude ||
  lastGPS.longitude !== data.longitude;

lastGPS = data;
lastGPSTime = Date.now();
```

`lastGPS = data` assigns `data` BY REFERENCE. `data` is an object; `lastGPS.latitude` on the NEXT call compares against the same object's latitude. If the *caller* mutates the `data` object between calls (unlikely but possible), the dedup check would be corrupted.

More realistically: if two calls to `updateGPS` arrive in quick succession via microtask fan-out (e.g., via a Promise.all firing multiple GPS handlers, each calling `updateGPS` with different coordinate objects), the dedup sees the first call's position (assigned to `lastGPS`), then the second call sees `lastGPS` pointing to the FIRST call's data (not the second's yet). This is actually correct behavior — positionChanged compares the NEW data against the PREVIOUS data. Good.

BUT: `lastGPS = data` holds a reference. If `data` is mutated externally after being stored (e.g., the caller reuses the same object and overwrites fields), the NEXT `updateGPS` comparison would be against the mutated version, not the historical snapshot. This is a contract concern, not a TTM bug per se.

**Impact:** None with the current callers (both `nav.updateGPS` call sites pass fresh objects). Latent concern.

**Proposed fix:** §E of the spec should add: "E11. `lastGPS` holds a reference to the caller's GPS data object. Callers MUST NOT mutate the object after passing it to `updateGPS`. The engine does not defensively copy. Future GPS source refactors that reuse an object across calls will silently break dedup." This is a DOCUMENTATION concern, not a runtime fix.

---

## Summary

- **MUST-FIX:** F2.1, F2.2, F2.3
- **SHOULD-FIX:** F2.4, F2.6, F2.7, F2.8, F2.10
- **NICE-TO-HAVE:** F2.5, F2.9, F2.11

**Most subtle race:** F2.3 — `deadReckonTick` calling `checkVoice` against a DR'd position that can LEAP over maneuvers, marking distant maneuvers' announcedSet keys before the user has actually reached them. On return-to-real-GPS, skipped maneuvers never fire their prompts (locked out) AND the prematurely-marked distant maneuver prompt was delivered at the wrong moment. This is the TTM-equivalent of voice-picker's F2.1 — state mutation across an asynchronous boundary (GPS outage + DR + recovery) where the mutation persists but the trigger context is no longer valid.

**Most load-bearing for field safety:** F2.7 — `currentManeuverIdx` derived purely from `findManeuverForSegment(snap.segmentIndex)` is non-monotonic and rate-unlimited. GPS glitches that jump segment-index forward-then-back can lock future maneuvers' announcements. Recommend adding monotonicity to `findManeuverForSegment` (never return less than current) in the same PR, even though §NG4 declares reroute trigger logic out of scope — this is checkVoice-adjacent and directly affects G1/G2 invariant holding in field conditions.

**Canonical remedy pattern:** F2.1's "capture seq at scheduling time, range-check in the timeout callback" is the same pattern voice-picker R2 recommends for `activePreviewUtterance` generation counters. Apply both specs together: adopt a consistent generation-counter idiom across nav.js and voice-picker.js for all timer-delivered state mutations.

**Spec-authoring recommendation:** Add an §E10/E11 batch documenting the reroute-never-applies case (F2.4), the GPS-mutation contract (F2.11), and the test-mock timing requirements (F2.10). These are not runtime fixes but plug documentation holes that could mislead subagents executing the plan.
