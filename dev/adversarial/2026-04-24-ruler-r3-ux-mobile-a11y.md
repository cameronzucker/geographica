# Ruler / measurement tool — adversarial review R3: UX / mobile / accessibility

**Reviewer:** Agent `cholla`
**Round:** 3 of 5 (UX / mobile / a11y lens)
**Spec under review:** `docs/superpowers/specs/2026-04-24-ruler-design.md` v1
**Date:** 2026-04-24

## Summary

The spec is engineering-tight on state machine, geodesy, and module boundaries — but UX/mobile/a11y is roughly half-specified. The headline gaps:

1. **Touch target sizes are well below WCAG 2.5.5 and Apple HIG.** A 16-px diameter vertex circle is unreachable with a glove on a moving vehicle. The spec says nothing about an invisible expanded hit area; without it the tool is unusable in the field, which is Geographica's headline use case.
2. **iOS Safari touch handling is hand-waved.** `e.preventDefault()` in pitfalls is necessary but not sufficient — MapLibre's own touch handlers, `touch-action` CSS, the 300ms tap delay (PWA standalone mode), and synthetic mouse events all need explicit treatment. The spec's tap-vs-drag flow doesn't survive realistic iOS Safari sequencing.
3. **The 5px / 200ms tap-vs-drag thresholds are guessed, not field-tested.** 200ms is shorter than the typical glove press; 5px is shorter than vehicle hand-jitter. Both will misfire on the only audience that matters (operators in vehicles or on antenna sites).
4. **No accessibility commitment.** Existing Geographica frontend has near-zero ARIA (one mic button has `aria-label`, that's it). The spec does not improve the baseline — there are no role/aria-selected on tabs, no live region for the mode banner, no meaningful description of the sparkline SVG, no skip/focus management for the floating banner.
5. **The banner-stacking open question (§5) is dodged.** Nav uses `#nav-banner` *inside* `#nav-overlay` (full-width, top, z-index 18). The proposed `#ruler-mode-banner` collides head-on. The spec must pick a resolution before the plan is written.
6. **Color contrast is not measured.** #ffd400 yellow-on-white-halo is the *line color*, but #ff7a00 orange on a white-tile basemap, and the inline-banner palette, have no contrast measurement. Field-readable claims need numbers.
7. **"Insert After" target placement is unconstrained.** A user can tap 100 miles off-segment after arming Insert After and get an inserted-but-geographically-meaningless vertex. The spec should constrain (project to nearest point on segment, or refuse if too far).
8. **Discoverability of vertex-selectability is missing.** In editing mode, vertex circles look identical to drawing-mode placement markers. A new user has no affordance signaling "tap me to see options."

I count **3 CRITICAL**, **8 MAJOR**, **5 MINOR** issues below.

---

## Findings

### CRITICAL-1 — Vertex hit targets fail WCAG 2.5.5 and Apple HIG; field use is impossible

**Spec evidence:** §C #3 (vertex rows ≥44px) but §D table sets `ruler-vertex-circles` at radius 8 (16px diameter) and selected at radius 11 (22px diameter). §C "Mobile considerations" claims 44px for *rows* but is silent on *map circles*.

**Reality:**
- WCAG 2.5.5 (Target Size, Level AAA) requires 44×44 CSS px minimum.
- Apple HIG and Material Design both require 44pt / 48dp touchable area minimum.
- Existing Geographica `.map-btn` is 36×36 — already a known gap, but at least nav-relevant buttons can be reached from a fixed position. Vertex circles are scattered targets the user must precisely hit while the map may be sliding or zooming.
- Field-use scenarios in CLAUDE.md (AREDN ops "antenna-aiming, field-navigation") imply gloved fingers and outdoor conditions where every target shrinks visually.

**The 16-px circle is the visual; there must be an invisible hit-test halo at 44+px diameter.** The spec must specify:
- Either a separate, invisible-but-pickable transparent circle layer with `circle-radius: 22` (44 px) and `circle-color: rgba(0,0,0,0)` or with low opacity, sitting above `ruler-vertex-circles`, OR
- A hit-test step in the touchstart handler that tolerates the nearest vertex within ~22 px regardless of MapLibre's `queryRenderedFeatures` result.

Without this, the feature is demonstrably unusable in the field. **This blocks the plan.**

**Recommended fix:** Add `ruler-vertex-hit-circles` layer at `circle-radius: 22, circle-color: rgba(0,0,0,0.001)` (just non-zero so MapLibre's hit-test counts it). All `mousedown`/`touchstart` listeners hit-test against this layer; only the visual radii stay at 8/11.

---

### CRITICAL-2 — iOS Safari touch model is under-specified and will produce visible misbehavior

**Spec evidence:** §D "Drag-to-reposition (touch): equivalent flow via `touchstart` / `touchmove` / `touchend`" + §F "Touch events must call `e.preventDefault()` to suppress synthetic mouse events on iOS."

**Reality — what actually happens on iOS Safari when a user puts their finger on a vertex:**

1. **MapLibre owns the canvas's touch events.** MapLibre attaches its own `touchstart/move/end` for pan, pinch-zoom, two-finger rotate. If the spec adds raw touch listeners directly to `map.getCanvas()` or the map container, they compete with MapLibre's gesture machinery. MapLibre's recommended pattern is `map.on('touchstart', ...)` (or `mousedown`, which MapLibre normalizes from touch) — NOT raw DOM listeners. The spec should explicitly say which is used.

2. **`e.preventDefault()` on `touchstart` requires `passive: false`.** Modern browsers default touch listeners to `{ passive: true }`. If the listener is attached via `addEventListener('touchstart', fn)` without explicitly passing `{ passive: false }`, the call to `preventDefault()` is silently ignored, and synthetic mouse events DO fire. This is a real bug, not a theoretical one.

3. **The 300ms tap delay** is mostly gone in modern iOS Safari **except** when the page is missing `<meta name="viewport" content="...">` with a defined width — Geographica has `width=device-width, initial-scale=1.0` so it should be fine, but `touch-action: manipulation` on map controls still prevents subtle delays. The spec should add `touch-action: manipulation` to vertex hit areas or related interactive elements.

4. **Synthetic mouse events on iOS Safari** fire ~300ms after `touchend` if and only if the touch sequence was a "click candidate" — short, small motion. Even with `preventDefault()` on touchstart, if MapLibre re-emits a click via `map.on('click')`, that handler will fire. This is exactly the path that triggers the reverse-geocode popup at app.js:1622. The `isActive()` mode-flag suppression must cover the synthetic click after a tap-on-vertex too — the spec only suppresses for `drawing`/`inserting`, but the *editing* state's tap-on-vertex must also not bubble up to reverse-geocode. The spec text in §B says "tap empty map → falls through to existing reverse-geocode handler" — but the handler at 1622 doesn't currently distinguish "tap on vertex" from "tap on empty map" because MapLibre `click` events fire regardless of which feature is under the cursor unless the inner handler checks `queryRenderedFeatures`.

5. **iOS Safari standalone PWA mode** has different touch semantics than tab mode. The spec doesn't mention PWA; if Geographica is ever installed (it's plausible — offline-first app), the touch model shifts.

**Recommended fix:** Spec must add a §D.5 "iOS Safari touch contract" subsection with:
- Use `map.on('touchstart' | 'mousedown', ...)` via MapLibre's normalized event API; do NOT attach raw DOM listeners on `map.getCanvas()`.
- Confirm in code that `passive: false` is set wherever `preventDefault()` is needed.
- Add `touch-action: manipulation` to `#ruler-mode-banner` and any sidebar action buttons.
- Existing reverse-geocode handler at app.js:1622 must also early-return when the click feature-list contains `ruler-vertex-circles` or `ruler-vertex-hit-circles`. Today the handler only checks 5 layer names; ruler layers must be added.
- Document expected behavior under PWA standalone mode (or explicitly defer with reasoning).

---

### CRITICAL-3 — `#ruler-mode-banner` collides with `#nav-banner`; spec dodges Open Question 5

**Spec evidence:** §D "Floating mode banner ... top-center of map ... Styled to not stack with `#nav-banner`." Open Question 5: "Likely yes — the spec assumes nav-active and ruler-active are mutually exclusive in practice, but no enforcement."

**Reality:**
- `#nav-banner` is *inside* `#nav-overlay` which is `position: absolute; top: 0; left: 0; right: 0; z-index: 18` (style.css:1270). It is a full-width banner, not a "top-center" one. When nav is active, `#nav-overlay` occupies the top of the screen with the instruction card, status bar, and banner. The "top-center" of the map is *below* the nav overlay (the map is offset by the variable `--nav-overlay-height`).
- A new `#ruler-mode-banner` placed at "top-center of map" with no z-index discipline will either:
  - Stack BELOW `#nav-overlay` (z-index 18) and be invisible during nav, OR
  - Stack ABOVE everything and obscure the nav instruction.
- More fundamentally: **can a user run nav and ruler simultaneously?** The spec says "spec assumes mutually exclusive in practice." But:
  - A user could plausibly be navigating to a trailhead and want to measure a side-hike from the trailhead while nav is paused/idle/at-destination. This is a real workflow.
  - If they open Measure tab during active nav, the proposed banner conflict happens immediately.
  - If they enter nav while a measurement is in `editing` state, ruler doesn't draw a banner, but `isActive()` is `false` so nothing breaks. OK.
  - But entering Measure tab while in `drawing` requires a banner, AND a sidebar full of controls — but on mobile sidebar overlays the map; nav overlay is also visible behind sidebar. This is genuinely ambiguous.

**Resolution options the spec must pick:**

A) **Hard mutual exclusion** — opening Measure tab during active nav shows a "Measurement is unavailable during navigation" empty-state in the panel; user must stop nav first. Cleanest, most testable, but rejects a real workflow.

B) **Banner replacement** — when ruler is active and nav is active, the ruler banner replaces `#nav-banner` (re-uses the same DOM slot inside `#nav-overlay`). Ruler banner styled like `.recalculating` etc. for visual consistency. Clear precedent in `.recalculating`, `.gps-stale`, etc.

C) **Banner stack** — ruler banner appears BELOW `#nav-overlay` (top: calc(var(--nav-overlay-height) + 8px), z-index 17). Compatible with the existing pattern at style.css:1605.

My recommendation: **(B)** — add ruler-banner classes (`#nav-banner.ruler-drawing`, `.ruler-inserting`) that piggyback on the existing nav-banner machinery. If nav isn't active, the floating banner uses option (C)'s positioning standalone. This keeps the contract: "there is at most one top-of-screen banner at a time."

This question must be **closed** in the spec, not left as an Open Question. The plan can't be written without a definitive answer.

---

### MAJOR-1 — Tap-vs-drag thresholds (5 px AND 200 ms) are not field-validated

**Spec evidence:** §D "Tap-vs-drag disambiguation: `mousedown`/`touchstart` followed by `mouseup`/`touchend` within 5 px AND 200 ms = tap." §F also lists this. Open Question 4 acknowledges the question for gloved fingers.

**Reality:**
- Capacitive touch with a glove (even thin tactical gloves) increases the contact-patch jitter from ~2 px (bare finger) to ~5–8 px easily. 5 px threshold means many gloved taps register as drags.
- 200ms tap is short. Native iOS tap-vs-press distinction is often closer to 500ms (long-press). 200ms means a slow, careful tap can be misread as a drag.
- Vehicle hand-jitter at 60 mph on a moderately uneven road can produce 10+ px finger movement before the user even intends to move. Vehicle use is a documented Geographica use case (nav voice-picker spec, wake-lock spec).

**Recommended fix:** Spec must specify how thresholds were chosen and either:
- Make them configurable (`localStorage`-backed dev knob, like `voice-picker-mock` pattern), with field-test cycle planned to tune values, OR
- Cite a primary source / measurement / precedent (e.g., Mapbox Studio uses 4px/100ms; CalTopo uses XYZ).

I'd argue the right defaults are **8 px AND 250 ms** for v1, with a comment that field-test feedback should iterate the values. The current "5 / 200" values look like they came from a desktop-centric mental model.

---

### MAJOR-2 — No screen-reader story for the map content; sparkline accessibility is absent

**Spec evidence:** §C #5 ("250×80 px SVG sparkline ... selected-vertex draws a vertical guide line"). No mention of ARIA, no description text, no fallback for screen-reader users.

**Reality:**
- VoiceOver / TalkBack will announce a `<svg>` with no `role`, `aria-label`, or `<title>` as "image" or skip entirely. The user gets no information about elevation profile.
- The vertex list rows in the sidebar are presumably plain `<div>`s based on the existing `.waypoint-row` precedent (style.css:367) — those would announce only the visible text. With proper `role="list"` + `role="listitem"` and `aria-label` on the row's coordinate display, they'd be navigable.
- The "drawing mode" banner is a transient notification — it should be a `role="status"` or `aria-live="polite"` region so screen-reader users know they entered drawing mode.
- Esc to exit drawing mode is fine, but focus-restoration after exit isn't addressed. Where does focus go when the user presses Esc? Probably nowhere — focus stays wherever it was, which on first-tap likely means the map canvas (which is not focusable by default).

**Existing baseline:** Geographica frontend has near-zero ARIA today (search confirmed: only `stt.js` mic button has `aria-label`, only `silent-video-lock.js` has `aria-hidden`). The voice-picker spec also did not introduce ARIA. The sidebar tabs have no `role="tab"` / `aria-selected`.

**Recommended fix:** Spec adds §C.7 "Accessibility":
- `<svg>` sparkline gets `role="img"` + `aria-label="Elevation profile: X meters gain, Y meters loss, ranging from Zmin to Zmax"` derived from computed stats.
- Vertex list: `<ol role="list">` with rows as `<li role="listitem">` + per-row `aria-label="Vertex 3 at 33.45° North, 112.07° West, segment ahead 1.2 miles bearing 045°"` so a screen reader gets a complete spoken summary on focus.
- Mode banner: `aria-live="polite"`, `role="status"` so a transition into drawing mode is announced.
- "Tab" key navigates vertex rows; Enter/Space activates "select"; Delete key on focused row deletes vertex (with confirmation? or with Undo?).

This is a real accessibility-floor lift, beyond what existing Geographica commits to. If Cameron's project ethos values "professional polish," the ruler is a natural place to set the bar — but the spec must commit to it explicitly.

---

### MAJOR-3 — Color contrast unmeasured for #ffd400 / #ff7a00 on real basemaps

**Spec evidence:** §D table lists colors but no contrast ratios. Goals state "Field-readable in sunlight (high-contrast palette)."

**Reality:**
- WCAG 2.1 SC 1.4.11 (Non-text Contrast) requires **3:1** for UI components and graphical objects.
- WCAG 2.1 SC 1.4.3 (Contrast Minimum, AA) requires **4.5:1** for normal text.
- #ffd400 (yellow) on **white** (positron basemap fully zoomed out): contrast ratio ≈ **1.07** — fails 1.4.11 catastrophically. The white halo around the line saves the *line itself* but not vertex circles, which fill with #ffd400 on a white tile background. The spec puts a 2-px white stroke around them; the *outer* edge of that stroke against a white tile is invisible.
- #ff7a00 (orange) on white: contrast ≈ **2.64** — also fails 1.4.11.
- On dark-matter basemap (#1e1e2e family), both #ffd400 and #ff7a00 hit ~10:1+. Fine.
- Hybrid imagery (NAIP, Sentinel-2): basemap is photographic, both bright and dark patches in same view. Yellow may disappear over wheat fields; orange may disappear over autumn-leaf areas. Real risk.

**Recommended fix:**
- Add contrast measurements per basemap mode in the spec.
- Promote vertex circle outline (currently 2-px white) to a darker outer ring: e.g., 2-px white *and* 1-px dark-navy outside, so circle visibility doesn't depend on basemap.
- Selected-vertex orange #ff7a00 → consider a darker orange like #d65a00 or render the selection ring using a contrast inversion (stroke #000 outside the white halo).
- Or, simpler: add a `prefers-contrast: more` media-query alternate palette that bumps both colors to higher-contrast equivalents.

---

### MAJOR-4 — "Insert After" tap is unconstrained; user can drop a vertex 100 miles off-segment

**Spec evidence:** §B "`inserting`: Map tap commits insert (new vertex selected)". §F doesn't list the case "tap is far from any segment."

**Reality:**
- User taps `[Insert After]` on V3 (between V3 and V4 on the original path).
- Banner says "tap to place new vertex."
- User taps somewhere on the map.
- Spec implies the tap location becomes the new vertex's coordinate, inserted between V3 and V4 in the index sequence.
- There's no constraint that the tap is *near* the V3-V4 segment.

So the user can produce: V1 → V2 → V3 → V_far_off_screen → V4 → V5, where V_far_off_screen is 1000 km away in the wrong direction. The vertex list shows correct numbering but the line zig-zags wildly.

This is technically the user's fault, but UX-wise it should be defended against:

**Option A — constrain to segment projection:** Tap location is projected to the nearest point on the V3-V4 segment. Visual ghost-preview during inserting mode shows where the vertex will land. Like CAD "snap to line."

**Option B — tap-and-confirm:** Tap places a draft vertex; banner shows "Confirm" / "Move" / "Cancel" buttons; user confirms placement.

**Option C — proximity guard:** Tap > N pixels from the nearest point on the segment shows a transient toast "Tap closer to the segment to insert" and doesn't commit.

I'd pick **(A)** for v1. Less surprising, no two-step UX, matches what users expect from drawing tools.

**Recommended fix:** Spec §B inserting transition adds: "Tap point is projected to nearest point on the relevant segment (between V_n and V_{n+1} for Insert After V_n). The ghost-preview marker during inserting mode follows the segment-projected cursor position, not the raw cursor position."

---

### MAJOR-5 — Vertex selectability is undiscoverable in editing mode

**Spec evidence:** §C #4 "Selected-vertex action row — visible only when `selectedVertex !== null`." §C #3 "Selected vertex gets a 3px orange left border + accent background" in the sidebar list.

**Reality:**
- A new user finishes drawing, lands in editing mode. They see the line, the vertex circles, the sidebar list with stats. They want to delete a vertex. How do they discover the action row exists?
- The vertex circles in editing mode look identical to the placement markers in drawing mode — no affordance signal.
- The sidebar list shows vertex rows but no hover/affordance hint that "click me to see options."
- The action row is hidden until selection — so the user doesn't even see it grayed-out.

This is a discoverability cliff. Compare to:
- CalTopo: hovering a vertex shows a small popover with "Delete / Insert Before / Insert After."
- Google Earth: vertex shows a small expand chevron.
- Mapbox Studio: vertex hover shows a delete-X badge.

**Recommended fix:** Spec must specify at least one of:
- Hover-state on vertex circles in editing mode (mouse-only, but a UX cue): pointer cursor + slight radius bump.
- Tooltip on first-vertex-hover in editing mode (one-time, dismissible) saying "Tap a vertex to edit."
- Empty-state copy in the action-row slot when no vertex is selected: "Tap a vertex on the map to edit, insert, or delete."
- A "Tip" badge after Finish that auto-hides after first interaction.

The empty-state copy approach is cheapest and most discoverable — the action row reserves its space and shows a placeholder hint.

---

### MAJOR-6 — Sidebar tab-persistence + ephemeral state is a confusing pair on reload

**Spec evidence:** Non-goals "v1 is purely ephemeral — measurements clear on tab switch, page reload, or 'Clear' button."

**Reality:**
- Existing app.js:1161 persists last-active sidebar tab to `localStorage.sidebar-last-tab`.
- User finishes drawing 5 vertices, lands in editing mode, has a measurement on screen.
- User accidentally reloads the page (or browser crashes, or sleep/wake on iPad kills the page).
- On reload: the sidebar restores to Measure tab (from localStorage), but the panel is empty (state was ephemeral). The user sees a blank Measure panel and a clean map.
- Especially confusing because the user just spent 30 seconds placing vertices.

**Options:**
- A) Snackbar/toast on reload-with-Measure-as-last-tab: "Measurements don't persist across reloads. Start a new measurement →." Disappears on first interaction.
- B) Empty-state in the panel with the same hint copy.
- C) Persist ephemeral state in `sessionStorage` so within-session reloads recover; cross-session reloads clear. Cheap: state object is already KMZ-serializable. SessionStorage survives reload but not tab close.

I'd pick **(C)** for the trivial cost. It removes the confusion entirely. (B) is the fallback if (C) is rejected for scope.

**Recommended fix:** Spec adds an explicit "Reload behavior" subsection: "Within-session reloads restore in-flight measurements via sessionStorage; cross-session reloads clear. Empty-state copy when panel is empty: 'Tap the map to start measuring.'"

---

### MAJOR-7 — Keyboard navigation coverage is incomplete

**Spec evidence:** §B mentions Backspace (pop last in drawing), Esc (cancel), Enter (finish). §F adds "Backspace pressed in a text input: handler checks tag." Tests include `test_keyboard.js` asserting Backspace/Esc/Enter/arrows.

**Missing:**
- **Tab key** through vertex list rows (focus management for keyboard-only users).
- **Space** to activate Insert Before / Insert After / Delete buttons (Space is the canonical "activate button" in addition to Enter).
- **Delete key** on a focused vertex row to delete (faster than navigating to the Delete button).
- **Arrow keys** the spec rejects as no-op. But for a focused row in the list, ↑/↓ should move focus to the previous/next row — that's standard list navigation. Sparkline scrubbing is correctly rejected; row navigation is not.
- **Esc on inserting** is documented; Esc on editing-with-selected-vertex should clear selection (spec doesn't say).

**Recommended fix:** Spec §C adds a keyboard-navigation table covering all states + keys, modeled on the §B state-machine table. Plan-writing step adds a `test_keyboard_full.js` scoped to the full table.

---

### MAJOR-8 — Mode banner has no exit-to-cancel for keyboard users on mobile

**Spec evidence:** §D "Has close `[×]` returning to `editing`."

**Reality:**
- The `[×]` is a tap-target on the banner. On a phone, the banner is at top-center; the user can tap it.
- But on iPad with an external keyboard (an actual AREDN field-use scenario — operators in the field with an iPad and Bluetooth keyboard), Esc must cancel, AND the close `[×]` should be focusable / Tab-reachable.
- Spec says Esc cancels (good). Doesn't say the `[×]` is focusable.

**Recommended fix:** Spec specifies the banner close button is a real `<button>` with proper focus styling, Tab-reachable, Enter/Space activates. The `[×]` is rendered as a real button, not a styled `<span>`.

---

### MINOR-1 — "Halo white" claim in §D is ambiguous

§D says vertex labels have "halo white" but doesn't specify halo width or whether halo is the SDF text-halo (MapLibre symbol layer attribute) or a CSS shadow. Since this is a symbol layer, `text-halo-color: #fff, text-halo-width: 1.5` is the right call, but the spec should be explicit because Open Question 8 already flags glyph-config concerns.

---

### MINOR-2 — Numeric format for bearing degrees not specified

Spec says "Per-segment **true** bearing in decimal degrees" and Goals say "decimal degrees." But: 1 decimal (045.0°) vs 0 decimal (045°) vs zero-padded (045°) — different conventions. AREDN antenna-pointing typically wants one decimal. Spec should say.

Also: bearing of 0° vs 360° — the spec normalizes to `[0, 360)` so it's always 0°, never 360°. Good. But due-east is 90.0°, due-south is 180.0° — confirm spec wants 0 = north (it does, standard great-circle). Document explicitly because aviation uses different conventions (e.g., 360 = north when displaying).

---

### MINOR-3 — Coverage warning badge color and copy not specified

§C #5 mentions "Coverage warning badge if gaps > 0%." What color? What copy ("8% no data" or "8% outside coverage")? Where positioned on the sparkline?

---

### MINOR-4 — Mobile bottom sheet vs. full sidebar not addressed

Spec assumes the existing sidebar machinery handles mobile. On viewport < 480px the sidebar becomes 85vw wide and overlays the map. With a measurement in flight, the user opens the sidebar to see stats, then needs to close the sidebar to interact with the map (tap/drag vertices), then re-open to see updated stats. This is high-friction on phones.

iOS native pattern is a "bottom sheet" that's swipe-up-to-expand, with a peek state showing key stats while letting the user touch the map. Out of scope for v1 but should be flagged as a known mobile UX limitation that may be revisited in a future "mobile UI polish" cycle.

---

### MINOR-5 — Bounded-mockup discipline: was the brainstorm mockup at sidebar width?

Spec says the mockup is at `.superpowers/brainstorm/.../measure-tab-mockup.html`. Per `feedback_bounded_ui_mockups.md`, mockups should match real container width (~320px sidebar on mobile, ~280–320px panel area). The mockup file is gitignored so I can't verify, but the plan-writing step should confirm the visual judgment was made at realistic width, not full-browser-width.

---

## Open questions resolved

**Q5 (banner stacking with #nav-banner):** Spec must resolve before plan. My recommendation: option (B) — re-use `#nav-banner` slot inside `#nav-overlay` via new classes (`.ruler-drawing`, `.ruler-inserting`). When nav inactive, ruler banner uses standalone positioning at `top: calc(var(--nav-overlay-height, 0) + 8px)`. Explicit precedence rule: nav banner wins if both states demand it (nav `recalculating` outranks ruler `drawing`).

**Q4 (touch threshold for gloves):** Defaults should be **8 px AND 250 ms** for v1. Spec should add a TODO for field-test calibration.

**Q1 (cancel in-flight tile fetches on drag-start):** Yes, cancel on drag-start AND on any state mutation. The spec already commits to AbortController; tighten to "any state mutation aborts the in-flight elevation run."

**Q7 (vertex list virtualization):** Not for v1. Cap at ~50 vertices in the data layer (not just rendering); soft-warn at 25 ("performance may degrade with very long paths"). Real users won't approach this.

**Q3 (long-path sample cap):** Acceptable as-specified. Add explicit ship-gate test: a 1000-mile path should still produce a usable distance + sparkline-with-warning, not a hung UI.

**Q2 (z=12 sample zoom):** Defer to other reviewers — this is a math/data question, not UX.

**Q6 (iOS Safari fetch throttling):** Defer to performance/concurrency reviewer.

**Q8 (SVG glyph reliability):** Defer to MapLibre version review.

---

## Recommended spec changes (delta to v1)

The spec should be revised to v2 with these additions/changes BEFORE the plan is written:

1. **§D layer table:** Add `ruler-vertex-hit-circles` (radius 22, near-transparent fill) above the visual circles. All hit-test goes through this layer. Update §F drag-vs-tap row to reference the new layer.

2. **§D new subsection D.5 "iOS Safari touch contract":** Specify use of MapLibre's normalized event API; document `passive: false`; add `touch-action: manipulation`; require reverse-geocode handler at app.js:1622 to skip when ruler vertex layers are under cursor; document PWA standalone-mode behavior or explicitly defer.

3. **§D drag-vs-tap thresholds:** Change to 8 px AND 250 ms; add a paragraph explaining the choice and flagging field-test follow-up.

4. **§C new subsection C.7 "Accessibility":** Define ARIA contracts for sparkline (role=img + aria-label), vertex list (role=list/listitem + per-row aria-label), mode banner (role=status, aria-live=polite), keyboard navigation table.

5. **§D color palette:** Add measured contrast ratios per basemap; darken vertex outline to a 2-color ring; specify `prefers-contrast: more` palette.

6. **§C #4 selected-vertex action row:** Add empty-state copy "Tap a vertex on the map to edit, insert, or delete." that occupies the row's space when no vertex is selected. Keeps the layout stable AND signals discoverability.

7. **§B inserting transition:** Add "Tap point is projected to the nearest point on the relevant segment; ghost-preview follows the projected position."

8. **§D floating banner:** Resolve Open Question 5 — re-use `#nav-banner` slot inside `#nav-overlay` via new classes; standalone-positioned at `top: calc(var(--nav-overlay-height, 0) + 8px)` when nav inactive. The `[×]` is a real `<button>`, Tab-reachable, focus-styled.

9. **§F new row "Page reload mid-measurement":** Update from "All state lost. By design (ephemeral v1)." to: "Within-session reloads restore via sessionStorage; cross-session reloads show empty-state with copy 'Tap the map to start measuring.'"

10. **§C new subsection C.6 "Keyboard navigation table":** Document all keys × all states (Tab, ↑/↓ for row focus, Space for button activate, Delete on focused row, Esc behavior in editing-with-selected-vertex).

11. **Update Goals:** Add "WCAG 2.1 AA color-contrast compliance for line, vertex, and selected-vertex on all three default basemaps (positron, dark-matter, NAIP imagery)." Currently the goals don't commit to WCAG, only to "Field-readable in sunlight (high-contrast palette)."

12. **Update §C mockup reference:** Note that the mockup must be re-rendered at realistic sidebar widths (~320 px desktop, ~85vw mobile) per `feedback_bounded_ui_mockups.md` and confirmed before plan-writing.

13. **Open Questions section:** Close 1, 3, 4, 5, 7. Leave 2, 6, 8 for other reviewers.

---

## Severity rollup

| # | Severity | Title |
|---|---|---|
| C-1 | CRITICAL | Vertex hit targets fail WCAG 2.5.5 / Apple HIG |
| C-2 | CRITICAL | iOS Safari touch model under-specified |
| C-3 | CRITICAL | `#ruler-mode-banner` collides with `#nav-banner` (Open Q5 unresolved) |
| M-1 | MAJOR | Tap-vs-drag thresholds (5px/200ms) not field-validated |
| M-2 | MAJOR | No screen-reader story; sparkline a11y absent |
| M-3 | MAJOR | Color contrast unmeasured (#ffd400, #ff7a00) |
| M-4 | MAJOR | Insert After tap is unconstrained |
| M-5 | MAJOR | Vertex selectability undiscoverable in editing mode |
| M-6 | MAJOR | Sidebar tab-persistence + ephemeral state confusing on reload |
| M-7 | MAJOR | Keyboard navigation coverage incomplete |
| M-8 | MAJOR | Banner [×] not specified as focus-reachable button |
| m-1 | MINOR | "Halo white" ambiguous in §D |
| m-2 | MINOR | Bearing decimal precision unspecified |
| m-3 | MINOR | Coverage warning badge color/copy unspecified |
| m-4 | MINOR | Mobile bottom-sheet vs. sidebar not addressed |
| m-5 | MINOR | Bounded-mockup width not confirmed |

The 3 CRITICALs all block plan-writing. The 8 MAJORs should each be either resolved in spec v2 or explicitly deferred with a written reason. The 5 MINORs are nice-to-haves that can be settled in the plan or deferred to v1.1.

---

*Reviewed by Agent `cholla` — UX / mobile / a11y lens, round 3 of 5.*
