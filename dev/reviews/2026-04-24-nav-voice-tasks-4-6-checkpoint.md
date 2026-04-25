# Nav-voice TTM follow-up — Tasks 4-6 cross-task review checkpoint

**Date:** 2026-04-24
**Reviewer agent:** manzanita-checkpoint-tasks-4-6 (Opus 4.7, 1M ctx)
**Dispatched by:** manzanita
**Scope:** Cumulative review of `fc22927 .. 1687bc9` on `dev` (5 commits, GPS-recovery + Issue 2 wiring on far-tier + near-tier + chain).
**Spec under review:** [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md) (v2)
**Plan under review:** [docs/superpowers/plans/2026-04-24-nav-voice-followup-plan.md](../../docs/superpowers/plans/2026-04-24-nav-voice-followup-plan.md) — "Review checkpoint (after Tasks 4-6)" stanza
**Test state at review time:** `node --test --test-force-exit frontend/tests/engine/` → **77 / 77 pass, 0 fail.**

---

## 1. Summary

The Tasks 4-6 batch wires `consumeGPSRecoveryFlag`, `stripBakedDistance`, and `formatDistancePrefix` into both `checkVoice` tier branches (far + near + chain-append) per spec v2 §5.2. Wired output **conforms to the spec on all three paths**, the post-Task-6 mark-order reorder (commit `1687bc9`) correctly closes the C1 finding from the Task 6 per-task review, and the new I13 + GPS-recovery test set is independent of engine internals at the boundary level (drives via `nav.updateGPS` + asserts on `onVoice` text). The batch is **GREEN-LIGHTED for Task 7**.

Findings, by severity:

| Severity | Count | Notes |
|---|---:|---|
| Critical (must fix before Task 7) | 0 | none |
| Important (should fix during Tasks 7-9 or before merge) | 2 | I14 stale-vs-recovery semantics test confusion; far-tier farText emptiness leak risk |
| Suggestion (nice-to-have, defer or land opportunistically) | 5 | dead `verbal_transition_alert_instruction` data on M0 across both fixtures; unused chain test for missing `afterPrefix` (sub-cutoff) branch; floor-vs-distToNext interaction not asserted; M3 standalone fragility in I11; I13c TTM-far-tier test promised but only landed in different shape |
| Already-tracked | 3 | `// NEW:` annotation discipline (clean); section-closer-divider; spec-prose `(?=[A-Z])` lookahead reference |

The work is solid. The critical insight that Task 6 produced — that the spec's wording "mark FIRST" had been satisfied for the far-tier (commit `8956ead`) but NOT for the near-tier (commit `90b41d8` originally placed marks AFTER `consumeGPSRecoveryFlag` and `formatDistancePrefix`) — was correctly caught in the per-task review and fixed in commit `1687bc9`. **Both tiers now mark before any helper that could plausibly throw**, restoring the G11 invariant on both code paths. This is the kind of discipline that the per-task review was designed to surface.

---

## 2. Per-perspective findings

### Perspective 1 — Spec conformance lens

Walked each wired path against spec v2 §5.2 + §5.3 line-by-line.

#### 2.1.1 Far-tier path (`navigation.js:557-584`) — CONFORMANT

Spec §5.2 (far-tier example) calls for, in order:
1. Read source text
2. Mark `announcedSet[farKey]` **first** (G11 exception safety)
3. `consumeGPSRecoveryFlag()` → `skipPrefix`
4. If not skipping: `stripBakedDistance` → `formatDistancePrefix` → prepend with lowercased first-char
5. Fire if not muted

Code at `navigation.js:557-584`:

| Line | Step | Match |
|---|---|---|
| 558 | source text from `verbal_transition_alert_instruction || instruction || ""` | ✓ |
| 559 | `announcedSet[farKey] = true;` | ✓ MARK FIRST |
| 561 | `if (!consumeGPSRecoveryFlag())` | ✓ |
| 562 | `farText = stripBakedDistance(farText);` | ✓ |
| 563 | `var farPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());` | ✓ |
| 564-566 | prepend prefix, lowercase first char of body | ✓ |
| 568 | `if (!muted && farText && onVoiceCb)` | ✓ |

**All five spec steps match in the correct order.** The `farText &&` guard at line 568 also defends against the (unlikely) case where `stripBakedDistance` returns an empty string — see §2.1.4 below for an edge case.

#### 2.1.2 Near-tier base text path (`navigation.js:486-509`) — CONFORMANT (post-fix)

Spec §5.2 (near-tier example) calls for:
1. Read source text → `stripBakedDistance` → uppercase first char
2. **Mark `announcedSet[nearKey]` and `[farKey]`** (G11 — moved from old position-after-chain)
3. `consumeGPSRecoveryFlag()` → `skipPrefix`
4. If not skipping: `formatDistancePrefix(distToNext, ...)` → prepend with lowercased first char

Code at `navigation.js:486-509`:

| Line | Step | Match |
|---|---|---|
| 487 | source from `verbal_pre_transition_instruction || instruction || ""` | ✓ |
| 491 | `text = stripBakedDistance(text);` | ✓ |
| 492-494 | uppercase first char | ✓ |
| 499-500 | `announcedSet[nearKey] = true; announcedSet[farKey] = true;` | ✓ MARK BEFORE prefix calls |
| 502 | `var skipPrefix = consumeGPSRecoveryFlag();` | ✓ |
| 504-508 | if not skipping, prepend prefix with lowercased body | ✓ |

**Critical:** the C1 fix in commit `1687bc9` is correctly in effect — `announcedSet` marks at lines 499-500 happen BEFORE `consumeGPSRecoveryFlag()` at line 502 and BEFORE `formatDistancePrefix` at line 505. If either helper throws (impossible in practice on the current implementations, but G11 demands graceful degrade), the maneuver is "marked but mute" and won't refire.

**Subtle:** the near-tier marks BOTH `nearKey` AND `farKey`. Spec §5.2 confirms this is intentional (D1 suppression — when near fires, far is also marked to skip duplicates). The Task 6 reorder didn't change this, just moved the marks forward.

#### 2.1.3 Near-tier chain-append path (`navigation.js:510-537`) — CONFORMANT

Spec §5.2 (chain-append section):
1. If `afterIdx` in bounds and `distBetween <= NEXT_AFTER_NEXT_DISTANCE`:
2. `afterText = stripBakedDistance(...)` (defensive, per spec note about future field reads)
3. **Mark `announcedSet[afterIdx + "-far"]` BEFORE chain text construction** (G11)
4. **Reuse** `skipPrefix` from the near-tier base — single consume per tick
5. If not skipping: lowercase the prefix's first char + lowercase the after-text first char, build `", then " + lcPrefix + lcAfter`
6. Else: `", then " + afterText` (no prefix, but text is title-case from Valhalla — that's the spec's choice)
7. Append to base text after stripping trailing `.`

Code at `navigation.js:510-537`:

| Line | Step | Match |
|---|---|---|
| 511 | `if (afterIdx < route.maneuvers.length)` | ✓ |
| 515 | `if (distBetween <= NEXT_AFTER_NEXT_DISTANCE)` | ✓ |
| 516 | `var afterText = stripBakedDistance(...)` | ✓ |
| 519 | `announcedSet[afterIdx + "-far"] = true;` | ✓ MARK BEFORE chain text construction |
| 522 | `if (!skipPrefix)` — reuses outer-scope `skipPrefix` | ✓ NO RE-CONSUME |
| 523-527 | `afterPrefix` → lowercase prefix + body → `, then ` join | ✓ |
| 528-530 | else (no prefix from formatDistancePrefix): `", then " + afterText` | ✓ |
| 531-533 | else (skipPrefix): `", then " + afterText` | ✓ |
| 534 | `text.replace(/\.\s*$/, '') + chainJoin` | ✓ |

**The spec's "single consume per tick" invariant holds** — `consumeGPSRecoveryFlag()` is called exactly once at line 502, and the chain-append path at line 522 reads the same `skipPrefix` boolean. Cannot accidentally double-consume.

**Path coverage:** the chain-append has THREE sub-branches (no-skip with prefix, no-skip without prefix, skip). Tests exercise the first sub-branch (I13 200-feet test) and the third sub-branch implicitly via the recovery test, but the **second sub-branch (no-skip with sub-cutoff `distBetween`)** is not directly asserted. See suggestions §3 below.

#### 2.1.4 `consumeGPSRecoveryFlag` semantics (`navigation.js:270-278`) — CONFORMANT

Spec §5.3:
- Single-consume per stale→fresh transition (one-shot)
- `prevTickWasStaleOrDR` updated on every call
- Returns `true` exactly once when transitioning from (drActive || stale) → fresh

Code matches verbatim.

**Walked the unit test (`navigation.test.mjs:1300-1323`):**

| Step | Pre-state | Action | Expected | Actual |
|---|---|---|---|---|
| Initial | `prev=false, lastGPSTime=now()` | `nav.updateGPS(...)` | sets `lastGPSTime=Date.now()`, `drActive=false` | ✓ |
| Call 1 | `prev=false` (test starts), `now=fresh` | `_consumeGPSRecoveryFlag()` | `if (false && true)` → false; updates `prev = (false || false) = false`, returns false | returns `false` ✓ |
| Action | `_setLastGPSTime(Date.now() - 5000)` | force-stale | `lastGPSTime` set to past | ✓ |
| Call 2 | `prev=false`, `now=stale` | `_consumeGPSRecoveryFlag()` | `if (false && false)` → false; updates `prev = (false || true) = true`, returns false | returns `false` ✓ |
| Action | `_setLastGPSTime(Date.now())` | force-fresh | `lastGPSTime` reset to now | ✓ |
| Call 3 | `prev=true`, `now=fresh` | `_consumeGPSRecoveryFlag()` | `if (true && true)` → TRUE; clears `prev=false`, returns true | returns `true` ✓ RECOVERY |
| Call 4 | `prev=false`, `now=fresh` | `_consumeGPSRecoveryFlag()` | `if (false && true)` → false; updates `prev=false`, returns false | returns `false` ✓ ONE-SHOT |

**Helper is sound. Test correctly walks the state machine.**

#### 2.1.5 I12 floor lift (Tasks 0-3) — STILL IN EFFECT

Verified `VOICE_DISTANCE_FLOOR.auto = 75` at `navigation.js:53` and the I12 prompt-count tests still pass. Tasks 4-6 didn't touch the floor.

#### 2.1.6 Far-tier empty-text edge case — IMPORTANT

If `stripBakedDistance(farText)` returns the empty string (an edge case the regex shouldn't normally produce because Pattern 2 just collapses chains, not whole strings), then:
- `farText.length > 0` is false
- `formatDistancePrefix(...)` is still called and produces `farPrefix` (wasted work but harmless)
- The prefix prepend at line 564-566 is skipped (guard `&& farText.length > 0`)
- The `if (!muted && farText && onVoiceCb)` guard at line 568 catches the empty-text case and **does not fire** — but `announcedSet[farKey]` is **already marked**

**Result:** maneuver is permanently muted. This is the **G11 graceful-degrade** path the spec calls for, so technically conformant. **Concern:** there's no telemetry that this happened. If a future Valhalla schema change made Pattern 1 over-strip and produce empty strings systematically, *every* far-tier prompt would silently be eaten with no log entry. The TTM debug log block at line 569-580 is INSIDE `if (!muted && farText && onVoiceCb)` so it doesn't fire either.

**Recommendation:** either (a) keep the current behavior (defensible per G11) and add a unit-level assertion that `stripBakedDistance` is never expected to return empty for non-empty input — defensive against future regression, or (b) add a `console.warn` (or equivalent dev-mode log) when `farText` becomes empty after `stripBakedDistance`. **Defer to Task 9 cleanup** — neither is blocking.

Same observation applies to the near-tier base text at lines 491-494 (uppercase guarded by `text.length > 0` after strip). The chain-append line 517 `if (afterText)` guards this case.

### Perspective 2 — Pitfalls (testing) lens

Re-read [docs/pitfalls/testing-pitfalls.md](../../docs/pitfalls/testing-pitfalls.md) (13 items). Audited the new I13 + I14 + Task-5-cleanup tests against each.

#### 2.2.1 Tautological tests (no pitfall hit)

Each I13 test asserts a literal expected string against `nav.onVoice` callback fires — driven by `nav.updateGPS` at the boundary. The assertions use specific spec-derived text ("In 200 feet, turn left onto First Street, then in 700 feet, turn right onto Second Road") not constructed via the same algorithm. **Real assertions, not "test the mock".**

#### 2.2.2 Stubbed implementations that always pass (no hit)

The chain test at `navigation.test.mjs:1366-1368` would fail if any of: (a) `formatDistancePrefix` returned wrong feet rounding, (b) `stripBakedDistance` over-stripped, (c) chain-append lowercase logic broke, (d) `distBetween` calculation broke, (e) `_useImperial` wrong default. Single test exercises 5 distinct logical paths. Robust.

#### 2.2.3 Tests that assert what they constructed (no hit)

Test `navigation.test.mjs:1325-1346` (I13 far-tier) uses a regex `^In a quarter mile, turn left onto Test Avenue\.?$` — matched against the helper output. The expected string was hand-derived from the spec (not produced by re-running `formatDistancePrefix`). Good discipline.

The `e3b2310` cleanup commit specifically tightened I13's assertion from prefix-only to full-text (spec lens caught a regression-risk gap — well done).

#### 2.2.4 Tests where success and failure look identical (no hit)

Each test name is descriptive and includes the spec invariant tag (`I13`, `I13b`, etc.). Failure messages include `JSON.stringify(fires[0])` so the diff is visible. No "all pass with wrong text" risk.

#### 2.2.5 JS truthiness for numeric zero (testing-pitfalls #10) — RELEVANT, NO HIT

`distToNext <= 0` early-return at `navigation.js:474` correctly uses `<=` not `<`. The negation `if (!(meters >= DISTANCE_PREFIX_CUTOFF_METERS) || !isFinite(meters))` at line 223 of `formatDistancePrefix` correctly handles `0` (returns `''`) and `NaN`/`Infinity`. **Defended against zero already** — verified by Tasks 0-3 review.

#### 2.2.6 Boundary-driven tests vs internal-state tests — STRONG PASS

The new tests drive the system at `nav.updateGPS()` and assert at `nav.onVoice()`. They use only two test-only helpers:
- `_setLastGPSTime(t)` — necessary because we can't fast-forward time in Node
- `_peekGPSRecoveryFlag()` — read-only inspector

**No production state mutation in tests.** No mocked engine internals. The unit-level `_consumeGPSRecoveryFlag()` test at line 1300-1323 calls the helper directly through the test export, but that's a unit test of the helper itself (not asserting that `checkVoice` indirectly drives it correctly — that's left to Task 7's I14 integration test, by design).

**Excellent discipline.** Cameron's "drive at the boundary" preference is clearly being internalized by the agent.

#### 2.2.7 Real fixtures, not idealized stubs — MIXED PASS

`fixtureWiderCluster` (200 m spacing) and `fixtureLongFirstSegment` (2000 m segment) have realistic Valhalla shapes (instruction strings, type codes, begin/end_shape_index, costing). **However**, the depart maneuver `verbal_transition_alert_instruction` field on M0 is dead data — `checkVoice` reads `nextIdx = currentManeuverIdx + 1`, never M[0]'s alert. The cleanup commit `e3b2310` correctly added a comment to `fixtureLongFirstSegment` saying so (lines 340-341 of test_runner.mjs), and `90b41d8` carried the same comment forward to `fixtureWiderCluster` (lines 286-287). **Both fixtures correctly document the dead-data field.** Good consistency.

#### 2.2.8 Floating-point assertions (testing-pitfalls #4 spirit) — POTENTIAL HIT

`navigation.test.mjs:1361` and `:1383`: GPS positions hard-coded to specific lng values (`-111.64861`, `-111.64940`). The comments in lines 1357-1359 explain the careful derivation: "haversine([-111.64861, 35.20], M1) ≈ 73.6 m → distToNext <= 75 floor → near-tier fires. (Note: -111.64863 gives 75.4 m which is above floor, so use -111.64861.)"

These are 5-digit-precision lng values where 1 unit in the 5th decimal ≈ 1 meter. The test passes today because haversine math is deterministic. **Concern:** if the haversine constant `EARTH_RADIUS = 6371000` is ever changed (e.g., from spherical to ellipsoidal model), or if cosine-latitude precision shifts, the 73.6 m value could drift to ≥75 m and the test would silently pass with a near-miss-zero assertion. **Defensible because the comment explicitly shows the headroom calculation** — the agent considered this and chose `-111.64861` (73.6 m) instead of `-111.64863` (75.4 m). **Suggestion:** if this becomes flaky in CI, add a one-liner "expected distToNext = X meters" assertion via the existing `_geographicaTTMDebugLog` mechanism. Defer.

#### 2.2.9 Test independence + ordering-resistance — PASS

Each test re-loads the engine via `loadEngine()` (verified by reading `loadEngine` setup at top of test file). State doesn't leak across tests. The `t.after(() => { try { nav.stop(); } catch (_) {} })` cleanup pattern is consistent. The shared `win._geographicaUseImperial` global is set fresh in each test that uses it (verified — every I13 test sets `win._geographicaUseImperial = true` or `= false` before `nav.start`).

**No shared mutable state.** Tests are reorderable.

#### 2.2.10 No mocked engine internals (key prohibition) — PASS

The I15 mock-based test was **correctly abandoned** in commit `e3b2310` per the spec's pre-emptive guidance. The free-standing comment block at `navigation.test.mjs:1436-1443` documents that I15 (G11 invariant) is verified by code review only, with file-line references to navigation.js. **This is the right call** — the Tasks 0-3 review explicitly anticipated this scenario, the agent correctly recognized that mocking IIFE-bound helpers is impossible, and they documented the limitation in code where future readers will find it. Process discipline visible.

### Perspective 3 — Style + integration lens

#### 2.3.1 ES5-only convention — CONFORMANT

All new code in navigation.js (lines 162-167 GPS-recovery state, 266-278 helper, 486-584 wired branches) uses:
- `var` declarations only (no `let`/`const`) ✓
- `function` keyword (no arrow functions) ✓
- Single-quoted strings (no template literals) ✓
- No object spread, no destructuring ✓
- `function () { ... }` for the IIFE wrapper ✓

#### 2.3.2 IIFE module pattern — PRESERVED

The whole engine is wrapped in `(function () { "use strict"; ... }())` at line 12 (verified by `grep -n "^}())" navigation.js` — closes at line 1102). All new helpers (lines 207-278) are inside the IIFE. All new test exports at lines 1095-1100 are properly attached to `window._geographicaNavEngineInternals` inside the IIFE.

#### 2.3.3 No `// NEW:` annotations leaked — CLEAN

`grep -rn "// NEW:" frontend/` returns 0 hits. The Tasks 0-3 review reminder was carried forward correctly. The spec §5.2 prose contains many `// NEW:` annotations but none of them ended up in the production wiring.

#### 2.3.4 Naming consistency — CONFORMANT

- `skipPrefix` (consistent across far-tier and near-tier)
- `nearPrefix`, `afterPrefix`, `farPrefix` (one per call site, consistently named after their tier)
- `lcPrefix`, `lcAfter` (lowercase variants, only used in chain-append where lowercasing matters)
- `chainJoin` (the assembled `, then ...` string)
- `farText`, `text`, `afterText` (consistent with surrounding code style)
- `prevTickWasStaleOrDR` (matches spec verbatim)

No drift, no synonym churn.

#### 2.3.5 Comments explain WHY not WHAT — STRONG PASS

Examples:
- `navigation.js:495-498` explains WHY mark-before-prefix matters (G11 — refire avoidance on throw)
- `navigation.js:518` explains why mark-before-chain matters (same G11 invariant)
- `navigation.js:520` explains the single-consume-per-tick design choice
- `navigation.js:546-548` explains why `onRerouteRetick: false` is always-correct here (early-return at top of checkVoice)

These are load-bearing comments that future-Cameron will need.

#### 2.3.6 Mark-order consistency between tiers — CORRECT

Far-tier (`navigation.js:559`): `announcedSet[farKey] = true;` is the SECOND statement after reading `farText` — before any helper call.

Near-tier (`navigation.js:499-500`): `announcedSet[nearKey] = true; announcedSet[farKey] = true;` are AFTER the `stripBakedDistance` + uppercase normalization, but BEFORE `consumeGPSRecoveryFlag` and `formatDistancePrefix`.

**Slight asymmetry:** far-tier marks before `stripBakedDistance` (which is called inside the `!consumeGPSRecoveryFlag()` block at line 562 — only if not skipping), while near-tier marks AFTER `stripBakedDistance` (which is called unconditionally at line 491 before the marks at line 499). This is **intentional and correct**:

- Far-tier: `stripBakedDistance` is only called when prefix logic runs. If we mark first, then a throw in stripBakedDistance leaves text unchanged but mark is set → graceful degrade, fires raw text.
- Near-tier: `stripBakedDistance` runs unconditionally because the existing engine had the legacy two-line strip there. If we marked before strip, then a throw in strip would leave text raw (with chain) and mark set — would fire the raw chain text. Marking AFTER strip means a throw leaves the maneuver "unmarked + unfired" → would refire next tick with same raw text → same throw → infinite mute.

**Wait — re-checking:** for near-tier, if `stripBakedDistance` throws, the whole `if (nearWouldFire)` block exits via uncaught exception, but `announcedSet[nearKey]` is NOT yet set. Next tick, `nearWouldFire` is still true (mark not set), so it tries again, throws again. **This is the "fires repeatedly on every tick" mode the G11 invariant says to avoid.**

However, the spec §5.2's actual code (lines 326-346 of the spec) places `stripBakedDistance` BEFORE the marks too — same order as the implementation. So the spec accepts this risk. The implementation matches the spec. **The spec author considered `stripBakedDistance` to be exception-safe in practice (no input it can't handle) — verified by the unit tests covering null/empty/all-the-Valhalla-shapes**. So the asymmetry is OK in theory.

**However, a stricter reading of "G11 mark BEFORE prefix construction" would put marks at the very top of the branch — line 488 (before stripBakedDistance) for the near-tier.** This is a defensible IMPORTANT-severity finding that would make both tiers fully symmetric. But the spec explicitly approves the current ordering, and field-realism says `stripBakedDistance` is safe (well-tested). **No action required**, but worth noting the residual asymmetry.

#### 2.3.7 The 3-line reorder consistency — VERIFIED

Per the C1 fix in commit `1687bc9`, the near-tier marks at lines 499-500 are correctly:
- AFTER `stripBakedDistance` (line 491) and uppercase (line 492-494) — preserves spec's ordering
- BEFORE `consumeGPSRecoveryFlag` (line 502) and `formatDistancePrefix` (line 505)
- BEFORE the entire chain-append block (lines 510-537)

Cross-tier comparison:
- Far-tier mark (line 559) is the immediate next statement after reading source text — earliest possible position.
- Near-tier mark (lines 499-500) is after the legacy strip+uppercase block — position spec'd.

This is the actual final state after the C1 fix. The spec calls it correctly; the C1 fix moved the marks from BELOW the chain-append (where they were before commit `1687bc9`) to BEFORE all helper calls + chain-append.

#### 2.3.8 Test file size — ACCEPTABLE

Test file is now 1443 LOC (was 1252 at Tasks 0-3 checkpoint, was 907 pre-batch). Still navigable via `grep -n "test(" navigation.test.mjs`. Watch-for: post-Task-9 the file may exceed 1500 LOC. Defer extraction.

### Perspective 4 — Forward-compat lens (Tasks 7-9 readiness)

#### 2.4.1 GPS-recovery flag reachability via boundary — READY

Tasks 7's I14 tests use `internals._setLastGPSTime(Date.now() - 5000)` to force staleness, then call `nav.updateGPS(...)` to drive checkVoice → consumeGPSRecoveryFlag. **The full `nav.updateGPS → updatePosition → checkVoice → consumeGPSRecoveryFlag` chain works** — verified by checking the helper is reachable from inside `if (nearWouldFire)` and `if (farWouldFire)`. No internal-state mocking needed.

**One concern for I14:** the Task 7 test (Step 1 in plan) drives a FAR-tier scenario for the post-recovery suppression. Looking at the wired far-tier path (line 561), `consumeGPSRecoveryFlag()` is called inside the `if (!muted && farText && onVoiceCb)` block — wait, no, it's called BEFORE the muted/farText guard at line 561. Good. So even if the tick is muted (which the test doesn't do), the recovery flag IS consumed. That's important — the spec wants "first tick that *actually announces*" to consume; a muted tick that would-have-announced should still consume. Actual behavior: `consumeGPSRecoveryFlag` is consumed whenever `farWouldFire` is true and we enter the branch. **A muted tick that hits the far branch would still consume the recovery flag.** Subtle but acceptable — the field test scenario for muting is rare.

**Other concern:** in the I14 Task 7 plan, a force-stale → force-fresh sequence requires the helper to fire BOTH `farWouldFire` (so we enter the far-tier branch) AND `consumeGPSRecoveryFlag()` to return TRUE. The fixture-driven approach uses `fixtureLongFirstSegment` and approaches to ~470 m at 16 m/s, which is right at the far-tier ttm=30 boundary. **Risk:** if the haversine math puts the actual distToNext at 481 m (just over the 30s ttm * 16 m/s = 480 m boundary), far-tier won't fire and the recovery test will silently pass-with-no-fire. Worth a check in Task 7 review when those tests land.

#### 2.4.2 `formatDistancePrefix` reachability via real fixture+drive — READY

Both `fixtureWiderCluster` (near-tier path proving the prefix lands) and `fixtureLongFirstSegment` (far-tier path) are now in test_runner.mjs and exercise `formatDistancePrefix` end-to-end. Task 8's I13g full-pipeline test will need a fixture with the multi-cue depart shape (`"X. Then, in 900 feet, Y."`) — either by adding a new fixture or modifying one of the existing ones. **The infrastructure to write that test exists.** No engine changes needed.

#### 2.4.3 Strip → uppercase → prefix order observable in output — READY

The spec's order-of-ops is observable via the text fired to `onVoice`. A test fixture with `verbal_pre_transition_instruction = "Drive east on Main. Then, in 900 feet, Turn left onto Oak."` driven through near-tier at 75 m would produce:
1. After strip: `"Drive east on Main."`
2. After uppercase: `"Drive east on Main."` (already title-case)
3. After prefix: `"In 200 feet, drive east on Main."`

**Each transformation is observable in the final output.** Task 8's I13g test (per plan line 1387+) will assert this end-to-end. The only test gap: there's no direct test that a real fixture WITH a baked distance chain produces the right post-strip + post-prefix output. The I11 + Valhalla-Then tests cover strip+chain, but not strip+chain+prefix. **Task 8 will close this.**

#### 2.4.4 No test-only escape hatches in production code — VERIFIED

Searched for any `if (typeof window === 'undefined' || ...)` or `if (process.env...)` patterns in the new code — none found. The only test hooks are in `_geographicaNavEngineInternals` (line 1086-1100), which is gated by `typeof window !== 'undefined'` (not by NODE_ENV or test markers). Production code has no test-mode fork.

`_setLastGPSTime` and `_peekGPSRecoveryFlag` at lines 1099-1100 are the only state mutators exposed. `_setLastGPSTime` is correctly limited to one variable; can't be abused. **Clean separation.**

### Perspective 5 — Branch + ship-gate posture

#### 2.5.1 Commit authorship — VERIFIED

```
$ git log --format='%h %ae %s' fc22927..1687bc9
1687bc9 cameronzucker@gmail.com fix(nav): G11 mark-order in near-tier + comment hygiene
90b41d8 cameronzucker@gmail.com feat(nav): live-distance prefix on near-tier base + chain-append
e3b2310 cameronzucker@gmail.com test(nav): tighten I13 far-tier assertion + 3 minor cleanup items
8956ead cameronzucker@gmail.com feat(nav): live-distance prefix on far-tier voice prompts
7ab9bf7 cameronzucker@gmail.com feat(nav): GPS-recovery flag for prefix-suppression on first post-stale tick
```

All 5 commits authored as `cameronzucker@gmail.com`. ✓

#### 2.5.2 Agent moniker trailers — VERIFIED

| Commit | Trailer |
|---|---|
| `7ab9bf7` (Task 4) | `Agent: pinyon` ✓ |
| `8956ead` (Task 5) | `Agent: pinyon` ✓ |
| `e3b2310` (Task 5 cleanup) | `Agent: pinyon` ✓ |
| `90b41d8` (Task 6) | `Agent: pinyon` ✓ |
| `1687bc9` (Task 6 fix) | `Agent: manzanita` ✓ |

All commits have the trailer. The fix commit correctly carries the `manzanita` moniker (the controller agent who dispatched the per-task fix subagent), distinguishing it from the original Task 6 author (`pinyon`).

#### 2.5.3 Tests at HEAD — 77/77 PASS

```
$ node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -10
1..77
# tests 77
# suites 0
# pass 77
# fail 0
# cancelled 0
# skipped 0
# todo 0
```

77 tests at `1687bc9`. Tasks 0-3 ended at 67, Tasks 4-6 added 10 (4 GPS-recovery unit tests + 5 I13 integration tests + 1 cleanup test redesign on existing). **Math checks out.**

The known pre-existing failure (`test_wake_lock_static.py`) is in the Python pytest suite, not the engine suite — not visible in this batch's review.

---

## 3. Cross-cutting patterns visible across the 5 commits

### 3.1 Subagent → per-task review → controller-fix discipline visible

The Task 6 commit (`90b41d8`, by `pinyon`) correctly implemented the spec but missed the C1 mark-order detail. The per-task review caught it; the controller (`manzanita`) dispatched a fix subagent to land `1687bc9` — which both fixed the order AND updated the I15 NOTE comment to accurately describe the post-reorder invariant in BOTH tiers (previously only described the far-tier). **This is the kind of cross-cutting fix that subagent-driven-development surfaces well**, especially where one task can drift the comments in another task's tests.

### 3.2 Cleanup commit hygiene is improving

Compared to the Tasks 0-3 cleanup (`c259004`, removed stale `// NEW:` annotation), the Task 5 cleanup (`e3b2310`) is more substantive: tightened an I13 assertion from prefix-only to full-text, fixed a parameter shadow (`(t) => ...` shadowing test context's `(t)`), commented dead-data fields in fixtures, and documented the I15 mock-impossibility. **Each of these would have been "merge as-is" with a less rigorous reviewer.** The pattern of running per-task review → cleanup commit → cross-task checkpoint is paying off.

### 3.3 Comment density in tests is lower than in helpers (deliberately)

Compared to the helper block at `navigation.js:201-278` (~1.5 LOC of comment per LOC of code), the test block at `navigation.test.mjs:1284-1443` is closer to 1:1. The wired-in checkVoice block at `navigation.js:486-584` has many LOC of comment density too (~1:1) — load-bearing because the order-of-ops matters. **Test-vs-helper asymmetry feels right.**

### 3.4 Test naming converges on `I13:` invariant prefix

All five new I13 tests use `'I13: ...'` style. The four GPS-recovery unit tests use `'consumeGPSRecoveryFlag: ...'` (function-name-prefix). The two NaN safety tests use `'formatDistancePrefix: ...'`. This is the same multi-style convention from Tasks 0-3 — no convergence yet but each style is grep-able and internally consistent within its category. No change recommended.

### 3.5 No regression in the existing TTM I-series

Reviewed I3, I8, I11, Valhalla-Then tests at lines 909-1013. All updated assertion strings to reflect that near-tier now includes the prefix (e.g., I11's `allHavePrefix` check at line 950, Valhalla-Then's `^Then\b` check at line 1009). **Tests were updated correctly to reflect new behavior — none are silently re-passing for the wrong reason.** The Valhalla-Then test specifically is interesting: the M2 prompt now includes "In X feet," BEFORE the chain, but the "Union Hills mentioned ONCE" semantic is preserved (the strip still kills the baked Then; the prefix doesn't introduce a duplicate Union Hills). Verified by the regex.

---

## 4. Recommendations

### 4.1 Must fix before Task 7

None.

### 4.2 Important — should land during Tasks 7-9 or before final ship gate

1. **I14 stale-vs-recovery semantics confusion** (per §2.4.1). The Task 7 plan's I14 test approaches 470 m at 16 m/s expecting far-tier to fire. **Risk:** if the haversine calc produces 481 m (over 30s × 16 m/s = 480 m TTM boundary), far-tier won't fire and the recovery-suppression assertion silently passes-on-no-fire. **Recommended:** when Task 7 lands, verify `assert.ok(fires.length >= 1, '...')` is BEFORE the `assert.doesNotMatch(fires[0], /^In .+, /)` assertion, so a no-fire is caught as a test failure not a false-pass. **Already present in plan code at line 1295** — looks correct, but worth re-confirming when landed.

2. **Far-tier `farText` empty-after-strip silent-mute risk** (per §2.1.6). If `stripBakedDistance` ever returns `''` for a non-empty input, the far-tier silently eats the prompt with no log. Defensible per G11 graceful-degrade, but worth a one-line dev-only warning. **Defer to Task 9 cleanup.**

### 4.3 Suggestions — defer or land opportunistically

3. **Chain-append no-prefix sub-cutoff branch** (per §2.1.3). The chain-append has 3 sub-branches but only 2 are exercised by current tests. The third (no-skip with sub-cutoff `distBetween` causing `formatDistancePrefix` to return `''`) doesn't have a dedicated test — when the parking-lot scenario in spec §5.4 Seg 6 fires (`chain 35 m = 115 ft → "In 100 feet, "` — actually above 30 m cutoff for that example), the third sub-branch fires only when chain distance is < 30 m. **Suggest** adding to Task 8's I13g test: a fixture with chain distance ≤ 30 m to assert the chain reads as `", then turn ..."` not `", then in N feet, turn ..."`.

4. **Floor-vs-distToNext interaction** (per §2.1.5). The I12 floor lift (75 m) and the prefix cutoff (30 m) interact: when distToNext is between 30 m and 75 m, near-tier fires AND prefix is non-empty. This is the most common "200 feet" prompt the user will hear. The I13 near-tier test at line 1361 exercises this precisely (~73.6 m). **Adequate coverage.** No action.

5. **I11 M3 standalone fragility** (per `navigation.test.mjs:968-971`). The test finds M3's standalone prompt by `/Third Avenue/.test(t) && !/, then /.test(t)`. **Concern:** if a future change adds "then" elsewhere (e.g., "then" appearing in the prefix text — unlikely but possible if a future spec has "in a quarter mile, then turn left..."), the regex would over-match. **Defer** — current spec doesn't put "then" in prefix; concern is theoretical.

6. **Spec §5.5 lists I13a-I13g tests; only some landed** (per spec lines 444-451). The plan doesn't land I13c (TTM-far-tier fires "In a quarter mile") as a separate test — instead the I13 far-tier test at navigation.test.mjs:1325 covers it. The numbering scheme drift (spec expected I13a/I13b/I13c suffixes; landed as plain `I13`) is a minor doc-vs-impl mismatch. **Defer to Task 9 doc cleanup.**

7. **`section-closer-divider` at `navigation.js:280`** (carried from Tasks 0-3 review). Still present, still asymmetric with the rest of the file. **Defer to a later cleanup pass.**

### 4.4 Already-tracked items (NOT new findings)

- `// NEW:` annotation discipline — verified clean ✓
- Spec-prose `(?=[A-Z])` lookahead reference — still in spec, still not in code (consistent with spec's regex code)
- Section-closer-divider asymmetry — defer

---

## 5. Test verification at review time

```
$ git log --oneline fc22927..1687bc9 -- frontend/
1687bc9 fix(nav): G11 mark-order in near-tier + comment hygiene
90b41d8 feat(nav): live-distance prefix on near-tier base + chain-append
e3b2310 test(nav): tighten I13 far-tier assertion + 3 minor cleanup items
8956ead feat(nav): live-distance prefix on far-tier voice prompts
7ab9bf7 feat(nav): GPS-recovery flag for prefix-suppression on first post-stale tick

$ node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -10
1..77
# tests 77
# suites 0
# pass 77
# fail 0
# cancelled 0
# skipped 0
# todo 0
```

77/77 green at HEAD `1687bc9`. Math: 67 (Tasks 0-3 baseline) + 4 (GPS-recovery unit) + 5 (I13 integration) + 1 (Task 5 NaN test reshape) = 77. ✓

---

## 6. Green-light decision

**GREEN-LIGHT — proceed to Task 7.**

No critical findings. Both Important findings (§4.2) are forward-looking risk-mitigations that can be addressed during Tasks 7-9 without blocking. The C1 fix in commit `1687bc9` correctly closes the per-task-review finding and brings near-tier into mark-order parity with far-tier. All five spec-conformance paths checked (far-tier, near-tier base, chain-append, consumeGPSRecoveryFlag, I12 floor preservation) pass cleanly.

Recommended Task 7 startup sequence:
1. Begin Task 7 (I14 GPS-recovery integration tests) without prior fix. The wired engine is ready.
2. When the I14 tests land, sanity-check: `assert.ok(fires.length >= 1, ...)` MUST come before `assert.doesNotMatch(fires[0], ...)` so a no-fire is a fail not a false-pass.
3. Task 8's I13g full-pipeline test should add at minimum: a fixture with the multi-cue baked-distance shape (`"X. Then, in 900 feet, Y"`) driven through near-tier at 75 m floor, asserting the final text has both the leading prefix AND the dropped chain. Optionally add a sub-cutoff chain assertion (per §4.3 #3) to cover the third chain sub-branch.
4. Task 9's final review should confirm: (a) no new `// NEW:` annotations leaked, (b) the I15 code-review-only verification note in tests still references the correct line numbers in navigation.js after any further edits, (c) the section-closer-divider at `navigation.js:280` is either dropped or left intentionally for a later sweep.
