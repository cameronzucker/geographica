---
round: 4
angle: Subagent executability
reviewer: general-purpose
date: 2026-04-20
---

# Round 4 — Subagent executability

Target spec: `/home/administrator/Code/geographica/docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md`

Verification against real source as of today:
- `frontend/nav-ui.js` line 141 = `function startNavigation() {` — correct.
- `frontend/nav-ui.js` lines 160–161 = `active = true;` / `document.body.classList.add('nav-active');` — correct.
- `frontend/nav-ui.js` line 164 = `primeSpeech();` — correct.
- `frontend/nav-ui.js` line 199 = `document.body.classList.remove('nav-active');` — correct.
- `frontend/navigation.js` line 633 = `function triggerReroute(...)` — spec says "off-route detector"; close enough but technically mis-labeled (the off-route *detector* is further up; line 633 is the reroute trigger).
- `frontend/navigation.js` line 683 = `setInterval(...)` in `startStaleChecker` — correct.
- `frontend/index.html` currently has scripts on lines 15, 18–20, 325–330 — `nav-ui.js` is at line 329. No existing wake-lock or nosleep reference. Vendor directory exists at `frontend/vendor/` with README documenting the "tarball from npm registry" update process, NOT a GitHub-release workflow.

Line-number claims hold RIGHT NOW, but the spec has no instruction to the subagent for what to do if they drift before execution (see F4.1).

## Findings

### F4.1 — Line-number references are fragile; no "search for the literal" fallback
**Severity:** SHOULD-FIX
**Location in spec:** §4.4, §1 "Files", and every `file.js:NNN` anchor
**Ambiguity:** The spec pins itself to exact line numbers (141, 160, 164, 199, 633, 683). Those numbers are correct at the moment of spec-writing but any intervening commit to `nav-ui.js` — even an unrelated bug fix during the r1-r3 adversarial window — will shift them. A subagent handed a stale line number will either (a) hook the wrong line, or (b) fail noisily and guess.
**Likely wrong interpretation:** Subagent opens `nav-ui.js`, scrolls to line 160, sees something unrelated (e.g., if a 2-line log statement was inserted above), decides the spec is wrong, and either hooks the new line 160 (semantically wrong) or hooks what it *thinks* the spec meant (semantically right but unverifiable).
**Proposed fix:** Add one sentence at the top of §4.4: "Line numbers are advisory, as of 2026-04-20. If they drift, locate the hook via the literal strings: for acquire, search for `document.body.classList.add('nav-active')` inside `function startNavigation()`; for release, search for `document.body.classList.remove('nav-active')` inside `function stopNavigation()`. Hook ONE line immediately after each."

### F4.2 — Two early returns above the hook point are not acknowledged
**Severity:** MUST-FIX
**Location in spec:** §4.4
**Ambiguity:** `startNavigation()` has two guard conditions above the spec's proposed hook point:
  - line 143: `if (!trip || !window.GeographicaNav) return;`
  - line 147: `if (!routeData) return;` (after `buildRouteData(trip)`)
The spec says "The `request('screen')` call is permitted only within a short grace window of a user-initiated event" and "startNavigation() is called synchronously from the Start-Nav button click handler" — but it does NOT state whether these pre-hook early-returns are desired (i.e., don't acquire wake-lock if there's no valid route) or undesired (i.e., we should acquire before any guard). A fresh subagent will probably leave the hook where §4.4 says (after line 161) and not notice the implication, which IS the correct behavior — but they might also decide "acquire even earlier to preserve the gesture window" and move the call above line 143, which would then acquire a lock for a nav session that never starts.
**Likely wrong interpretation:** Subagent moves `WakeLock.acquire()` to the very top of `startNavigation()` "to maximize gesture-window safety" per the spec's own emphasis in §4.1 on not losing the grace window. Result: lock held when no nav is actually running.
**Proposed fix:** Add to §4.4: "Note that `startNavigation` has two early returns above the hook point (missing trip, failed route-building). This is intentional — do NOT move the `WakeLock.acquire()` call above these guards. If no nav session starts, no lock is needed. The gesture window is preserved because all work between the click and line 161 is synchronous (no `await`, no `fetch`, no `setTimeout`)."

### F4.3 — `status()` return value boundary: `'none'` vs `'idle'` undefined
**Severity:** MUST-FIX
**Location in spec:** §4.3 ("Diagnostic — returns `'wakelock' | 'nosleep' | 'none' | 'idle'`") and §5.6 test ("`status()` returns `'idle'`")
**Ambiguity:** Four states, no definitions. Acceptance test in §5.6 expects `'idle'` after "call `release()` with no prior `acquire()`". What about: `acquire()` called but both paths failed (§5.4)? Spec says "`shouldBeActive` remains `true` but neither mechanism is active" — is that `'none'` or `'idle'`? `release()` after a successful acquire() — back to `'idle'` or `'none'`?
**Likely wrong interpretation:** Subagent A implements `'idle'` = "never acquired or fully released", `'none'` = "trying to hold but nothing works". Subagent B implements `'idle'` = `shouldBeActive === false`, `'none'` = `shouldBeActive === true && !sentinel && !noSleepActive`. Both pass §5.6's test. They diverge on §5.4's post-acquire state, and a downstream consumer (debug overlay, telemetry) will see inconsistent strings.
**Proposed fix:** Add a table to §4.3:
  - `'idle'`: `shouldBeActive === false` (never called acquire, or release was last call).
  - `'wakelock'`: `shouldBeActive === true && wakeLockSentinel !== null`.
  - `'nosleep'`: `shouldBeActive === true && wakeLockSentinel === null && noSleepActive === true`.
  - `'none'`: `shouldBeActive === true && wakeLockSentinel === null && noSleepActive === false` (intent-to-hold, no mechanism active; degraded mode per §5.4 or transient hidden-tab state).

### F4.4 — NoSleep.js file selection from v0.12.0 release is ambiguous
**Severity:** MUST-FIX
**Location in spec:** §4.2, §8
**Ambiguity:** Spec says "v0.12.0", links to the GitHub releases tag, and specifies target path `frontend/vendor/nosleep.min.js`. The v0.12.0 release ships several artifacts: `src/NoSleep.js` (unminified ES), `dist/NoSleep.js`, `dist/NoSleep.min.js`, and examples. The spec does not say which file to copy. The existing `frontend/vendor/README.md` documents an *npm-registry* tarball workflow, not a GitHub-release workflow, so the subagent's natural reflex (follow the existing vendoring pattern) sends them to npm for `nosleep.js`, which may ship a different file layout.
**Likely wrong interpretation:** Subagent grabs `src/NoSleep.js` (unminified, ES-module-style `export default`) because the filename looks right, renames it to `nosleep.min.js`, and it fails at load time because the module-level `export` tokens aren't valid in a regular `<script>` tag. Or: subagent grabs the npm tarball where the file is `NoSleep.js` (capital letters) and doesn't realize the `.min.js` suffix is aspirational.
**Proposed fix:** §8 should specify exactly: "Download from `https://github.com/richtr/NoSleep.js/releases/download/v0.12.0/NoSleep.min.js` (or the equivalent `dist/NoSleep.min.js` inside the repo at that tag). SHA256: `<add hash>`. Rename to `frontend/vendor/nosleep.min.js` (all lowercase, for consistency with existing vendored assets). License file: copy `LICENSE.md` from the repo root to `frontend/vendor/nosleep.LICENSE` and link from the vendor README."

### F4.5 — Vendor README update is not mentioned
**Severity:** SHOULD-FIX
**Location in spec:** §4.6, §8
**Ambiguity:** `frontend/vendor/README.md` has a table of included libraries with columns (Library, Version, Purpose). Spec adds a new vendored asset but does not instruct subagent to add a row. A subagent doing "exactly what the spec says" ships a vendored asset undocumented in the vendor README.
**Likely wrong interpretation:** Subagent adds `nosleep.min.js` and `nosleep.LICENSE` to `frontend/vendor/` but forgets README. Code review catches it later.
**Proposed fix:** Add to §10 acceptance criteria: "`frontend/vendor/README.md` table lists NoSleep.js v0.12.0 (MIT) with purpose `screen wake-lock fallback for non-Secure-Context origins`."

### F4.6 — "Do NOT" list in §4.4 is not exhaustive
**Severity:** SHOULD-FIX
**Location in spec:** §4.4 bottom
**Ambiguity:** §4.4 bans three wrong approaches (engine-level callbacks, hooking in sub-operations, try/catch at call site). Unbanned wrong-but-plausible variations a fresh subagent might pick:
  - Hooking via `MutationObserver` on `document.body.classList` (§5.13 says class-observer is wrong, but that's buried 40 lines away).
  - Moving `primeSpeech()` to be first, or combining `primeSpeech()` + `WakeLock.acquire()` into a single `primeUserGestureAPIs()` helper (F4.12 below).
  - Calling `WakeLock.acquire()` from a top-level `'visibilitychange'` or `'navigation-started'` custom event dispatched from `startNavigation` (adds async boundary, violates gesture window).
  - Guarding the acquire with `if (isSecureContext)` at the call site.
**Likely wrong interpretation:** Subagent "improves" the integration by factoring `primeSpeech()` + `WakeLock.acquire()` into a helper, breaking the strict-synchronicity invariant the spec elsewhere stresses.
**Proposed fix:** Expand the "Do NOT" list with three more entries: (4) Do NOT observe `nav-active` class changes via `MutationObserver`; hook both call sites explicitly. (5) Do NOT combine `WakeLock.acquire()` with `primeSpeech()` or any other call into a helper; two separate statements in `startNavigation`. (6) Do NOT gate `WakeLock.acquire()` behind `isSecureContext` at the call site — the module itself decides which path to use.

### F4.7 — Warning message format not prescribed
**Severity:** NICE-TO-HAVE
**Location in spec:** §4.1, §4.2, §4.3, §5.2, §5.3, §5.4
**Ambiguity:** Spec shows three warning strings (`'[wake-lock] navigator.wakeLock.request rejected'`, `'[wake-lock] NoSleep.js not loaded, no fallback available'`, `'[wake-lock] NoSleep.enable() threw'`) inside code snippets. Are these normative (must use exactly this string) or illustrative (any `console.warn` with `[wake-lock]` prefix)? §6.1 `test_no_cdn_urls_for_nosleep` is a grep; a future grep-for-warning-prefix test would care.
**Likely wrong interpretation:** Subagent reorders words, drops brackets, or localizes ("WakeLock request denied"); grep-based tests that look for `[wake-lock]` pass but anyone searching logs for a consistent prefix finds inconsistencies.
**Proposed fix:** Add to §4.6: "All console warnings emitted by this module MUST be prefixed with the literal string `[wake-lock] `. Use the exact warning strings shown in §4.1/§4.2 code snippets."

### F4.8 — Python test directory `tests/wake-lock/` may be treated as a Python module
**Severity:** SHOULD-FIX
**Location in spec:** §1 "Files", §6.2
**Ambiguity:** Spec says `tests/wake-lock/` is a NEW directory for Node JS tests. The repo's `tests/` dir has no `__init__.py` (verified), so pytest's rootdir-discovery already treats `tests/` as a plain directory. But: pytest 8.x will attempt to import any `.py` file under `tests/`, and Node-style `.test.js` files under `tests/wake-lock/` won't conflict directly. However, the subagent may be tempted to add an `__init__.py` or a `conftest.py` "to be safe", or may write a Python test helper inside that directory that gets double-collected. Also: directory name contains a hyphen — not a valid Python identifier, so if it ever DID get module-loaded it would fail.
**Likely wrong interpretation:** Subagent adds `tests/wake-lock/__init__.py` "just in case" and pytest crashes on import. Or: Subagent names it `tests/wake_lock/` (Python-safe) while the spec says `tests/wake-lock/` (Node-conventional), then static test #3 greps for a path that doesn't exist.
**Proposed fix:** Add to §6.2: "The directory MUST be named `tests/wake-lock/` (with hyphen). Do NOT add `__init__.py` or `conftest.py` inside it — this directory is not Python-discovered. The hyphen intentionally prevents Python import. Tests are run via `node --test tests/wake-lock/` from repo root."

### F4.9 — Python static tests are described but their grep patterns aren't pinned
**Severity:** SHOULD-FIX
**Location in spec:** §6.1
**Ambiguity:** Each static test has a one-line description. No regex, no path, no pass criteria beyond "grep for X". A subagent can write a regex like `/WakeLock\.acquire/` that ALSO matches `window.WakeLock.acquire = ...` (the wrong side — the module's own export, not the call site). Or a test that passes when the string is in a comment.
**Likely wrong interpretation:** `test_nav_ui_calls_wake_lock_acquire` is written as `assert 'WakeLock.acquire()' in open('frontend/nav-ui.js').read()`. Passes today. Passes tomorrow if someone adds a comment `// TODO: remove WakeLock.acquire()` elsewhere. Also passes if the call is moved outside `startNavigation`.
**Proposed fix:** For each static test, show the regex and the narrow scope. E.g., `test_nav_ui_calls_wake_lock_acquire`: "Parse `frontend/nav-ui.js`, locate the lines between `function startNavigation() {` and the matching closing `}` (tracking brace depth). Assert the regex `r'^\s*WakeLock\.acquire\(\);\s*$'` matches exactly one line within that range. Assert the immediately-preceding non-blank, non-comment line contains `document.body.classList.add('nav-active')`."

### F4.10 — JS unit tests list names and scenarios but not assertions
**Severity:** SHOULD-FIX
**Location in spec:** §6.2
**Ambiguity:** Each test is named (e.g., `test_primary_reject_falls_to_nosleep`) and its scenario described. No expected assertions. Two subagents can write "correct" tests with different assertions — e.g., one checks `NoSleep.enable was called`, another checks `status() === 'nosleep'` after, another checks the console.warn was emitted — all valid, but coverage overlaps and gaps differ.
**Likely wrong interpretation:** Subagent writes a test that only asserts `acquire()` didn't throw. Passes for every implementation, including a no-op one.
**Proposed fix:** For each of the 12 named tests in §6.2, add a one-line assertion sentence. E.g., `test_primary_reject_falls_to_nosleep`: "After `acquire()`, assert `mockNoSleep.enable` was called exactly once AND `status() === 'nosleep'`." Even three words per test ("mock X called, status Y") prevents divergence.

### F4.11 — Module pattern ambiguity: `async function acquire` inside IIFE
**Severity:** NICE-TO-HAVE
**Location in spec:** §4.3, §4.6
**Ambiguity:** §4.6 shows the IIFE skeleton with `async function acquire() { /* ... */ }`. §4.3 shows the concrete implementation using `async function acquire`. But `window.WakeLock = { acquire: acquire, ... }` exposes an async function — nav-ui.js calls it as `WakeLock.acquire();` and discards the returned Promise. The spec does not say whether the callers must `.then()` / `await` the result. §4.4 says "Must be called BEFORE any awaited promise or setTimeout/setInterval" — this is the CALLER's obligation, but a subagent may interpret "synchronous" to mean `acquire()` itself must be synchronous, refactor it to return nothing and kick off internal work via an immediately-invoked async IIFE, then lose the Promise chain.
**Likely wrong interpretation:** Subagent rewrites `acquire` as synchronous-looking (`function acquire() { (async () => { ... })(); }`) to match the caller's fire-and-forget pattern, loses exception handling around the rejection path.
**Proposed fix:** Add to §4.3: "The exported `acquire` is an async function. Callers invoke it as a bare statement (`WakeLock.acquire();`) and do NOT await the Promise — the call is fire-and-forget from the caller's perspective. The module internally awaits `navigator.wakeLock.request('screen')`; this await is acceptable because it's the FIRST await in the synchronous-from-click chain, preserving the gesture window per HTML spec."

### F4.12 — `primeSpeech()` at line 164 and the gesture-window invariant
**Severity:** SHOULD-FIX
**Location in spec:** §4.4 "Do NOT … Add a call in `primeSpeech()`"
**Ambiguity:** `primeSpeech()` is called at line 164, AFTER the proposed WakeLock hook at line 162. Both are gesture-window-sensitive. The spec bans moving `WakeLock.acquire()` INTO `primeSpeech()`, but does NOT address what happens if a future refactor reorders them or inserts an `await` between 161 and 164. More subtle: if a subagent "cleans up" by moving `primeSpeech()` to run BEFORE `nav.start(routeData)` on line 158, `nav.start` might internally fire a callback that (today) is synchronous but could later become async, and the chain breaks. The spec doesn't freeze the ordering.
**Likely wrong interpretation:** Subagent sees `WakeLock.acquire()` at 162 and `primeSpeech()` at 164, decides the gesture-sensitive calls should be "grouped", moves `primeSpeech()` up to 163. Harmless today. Later, someone adds a 3-line log between 161 and 162 that includes `await fetch('/api/nav-start-log', ...)`. Wake-lock acquire now fires post-await, rejects as out-of-gesture, falls to NoSleep which also fails — and nobody notices because the change was "just a log".
**Proposed fix:** Add to §4.4: "The ordering of lines 161 (class add) → 162 (WakeLock.acquire) → 164 (primeSpeech) is LOAD-BEARING. Do NOT reorder them. Do NOT insert any line between 161 and 164 that contains the token `await`, `fetch(`, `setTimeout(`, or `.then(`. Add a comment ABOVE line 162 in the implementation: `// DO NOT insert awaited work between classList.add and primeSpeech — breaks Screen Wake Lock + SpeechSynthesis user-gesture requirements.`"

### F4.13 — Manual field test (§6.3) as a blocker for agent-driven execution
**Severity:** MUST-FIX
**Location in spec:** §6.3, §10
**Ambiguity:** §10 acceptance criteria item 8 says "Manual field acceptance checklist (§6.3) completed on at least one Android phone." This is a ship-block according to §10 ("all must be true"). A subagent plan executed entirely by agents has no way to complete this item. Is the plan supposed to mark it as a human-in-the-loop gate, or is it a soft-blocker, or is the whole acceptance criteria list advisory?
**Likely wrong interpretation:** Subagent marks every checkbox and ships. Or: subagent marks item 8 complete with a "will be done later" note in the commit message. Or: subagent refuses to ship and stalls waiting for human input without a clear handoff signal.
**Proposed fix:** Rewrite §10 item 8 as: "Manual field acceptance checklist (§6.3) is DEFERRED to Cameron. The plan produces a separate PR-body checklist that Cameron runs after merge; agent-complete ≠ ship-complete. Until Cameron confirms, the feature is considered 'code-complete, field-untested'." Add to §11 (Open questions) or new §12: "Subagent handoff protocol: agent work terminates when static tests + JS unit tests pass and code is committed on dev. Manual field testing is Cameron's responsibility and its completion is tracked in the implementation log, not as a code-level gate."

### F4.14 — Acceptance criteria §10: no owner/mechanism for checkbox ticks
**Severity:** SHOULD-FIX
**Location in spec:** §10
**Ambiguity:** 10 checkboxes. Who ticks them? Spec doesn't say. In `/writing-plans` / `/subagent-driven-development` flow, does the plan inherit these as task gates (each box maps to a task), or are they a PR-review checklist, or a release-notes checklist?
**Likely wrong interpretation:** Subagent A treats §10 as "I'm done when all 10 are true, don't write tasks for them." Subagent B treats §10 as "each is a task I must create." The plan is either too thin (A) or duplicates the spec verbatim (B).
**Proposed fix:** Add a line above the list: "Each checkbox is a `/writing-plans` task gate — the implementation plan MUST include one Phase-Success-Criterion line that maps to each of these 10 items, with item 8 flagged as human-in-the-loop per F4.13."

### F4.15 — Zero deployment/rebuild guidance; nginx caching of index.html
**Severity:** MUST-FIX
**Location in spec:** (absent — not addressed anywhere)
**Ambiguity:** Spec adds two new `<script>` tags to `frontend/index.html` and two new files. Does this require `docker compose build frontend` / `docker compose up -d frontend` / `docker compose restart nginx` / wizard update / cache-buster query string? The spec is silent. If nginx serves `index.html` with cache headers that allow re-use, a beta tester on the Pi may receive the new `nav-ui.js` but the old `index.html` that doesn't `<script src>` wake-lock.js — so `WakeLock.acquire()` fires, `window.WakeLock` is undefined, and the nav-ui line throws a ReferenceError, taking down the nav start flow.
**Likely wrong interpretation:** Subagent commits, pushes, considers the job done. Nginx in prod serves cached index.html. Feature is dead in the field.
**Proposed fix:** Add §12 "Deployment": "No Docker rebuild required — frontend is served statically by nginx from bind-mounted `frontend/` directory. Nginx caches static HTML for up to 1 hour by default (`nginx/nginx.conf`). To ensure new scripts load on already-warm client caches, append a cache-busting query string to ALL script tags touched by this change, e.g. `<script src=\"wake-lock.js?v=20260420\">`. Alternatively, bump the `?v=` on every script tag in index.html. Also: nginx sub_filter is not used for script src rewriting — verify by grepping `nginx/` for `sub_filter.*script`."

### F4.16 — `status()` is not called by anyone, but defined — is it dead code?
**Severity:** NICE-TO-HAVE
**Location in spec:** §4.3
**Ambiguity:** `status()` is a public API but no §4.4 integration call site uses it and no test-list item (§6.2) uses it directly. It's diagnostic-only. Subagent may (a) skip implementing it since nothing calls it, (b) implement but leave untested, (c) add a hidden debug button.
**Likely wrong interpretation:** Subagent omits `status()` entirely as YAGNI. Static test `test_wake_lock_js_exists` still passes (it only checks for `window.WakeLock`). Failure mode is invisible until someone later tries to debug.
**Proposed fix:** Add to §6.1: "`test_wake_lock_js_exports_api` — parse `frontend/wake-lock.js`, assert the object assigned to `window.WakeLock` literally contains the keys `acquire`, `release`, `status` (regex `/window\.WakeLock\s*=\s*\{[^}]*\b(acquire|release|status)\b/` three times or a proper AST parse)." And to §6.2 add `test_status_returns_correct_values` covering all four return values from the table in F4.3.

## Summary

15 findings — 5 MUST-FIX, 7 SHOULD-FIX, 3 NICE-TO-HAVE — plus one correctness counter-check that the spec's line-number claims all hold RIGHT NOW (but F4.1 addresses their fragility). The biggest executability risks are: (F4.2) the two unreferenced early returns in `startNavigation`; (F4.3) undefined `status()` return-value semantics; (F4.4) ambiguous NoSleep.js file selection from a multi-artifact release; (F4.12) unfrozen ordering of gesture-window-sensitive calls; and (F4.15) no deployment/cache-busting guidance, which is the single highest-impact gap — a subagent ships correct code that nginx serves stale index.html around, and the feature silently does nothing in the field.

The spec is otherwise unusually thorough for adversarial review — concrete code snippets in §4.3, numbered failure modes in §5, and explicit "Do NOT" lists show prior-round review polish. The remaining gaps are the ones a fresh subagent would hit in the specific no-prior-context execution mode of `/subagent-driven-development`.
