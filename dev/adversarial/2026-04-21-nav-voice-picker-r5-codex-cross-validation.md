---
round: 5
angle: Codex cross-validation
reviewer: OpenAI Codex CLI (outside-Claude perspective)
date: 2026-04-21
---

# Round 5 — Codex cross-validation

Independent review from outside the Claude model family. Four Claude rounds (R1 API correctness, R2 concurrency, R3 testing, R4 subagent executability) ran in parallel; this round formed its own view first, then cross-checked for overlap. Six findings across offline/AREDN, accessibility, i18n, consistency, and one novel angle.

**Captured from Codex stdout output; writer recorded after transcription from the live stream.**

---

### F5.1 — Spec allows user to save a cloud-backed voice that silently fails on AREDN mesh

- **Severity:** MUST-FIX
- **Angle hit:** offline
- **Claim in spec:** §1: "No network dependency"; §7.1 step 3b/3c resolves from the current voice list without any `localService` filter; §6.1 exposes the full installed voice list in `#pref-voice-select`.
- **Issue:** On the browsers Geographica is most likely to encounter in the field, `speechSynthesis.getVoices()` can include cloud-backed voices with `voice.localService === false`. On an isolated AREDN mesh, those voices are not reliable even if they worked during setup on home Wi-Fi or LTE. The current spec therefore lets the user save a voice that will silently stop speaking once the device is truly offline. That directly contradicts the offline-first premise and turns a preference feature into a field failure mode.
- **Proposed fix:** Amend §7 and §8 so the default candidate set is `en-*` voices with `localService !== false`. In the specific-voice dropdown, either hide non-local voices entirely or place them in a clearly separated "Cloud voices (internet required)" opt-in section that is collapsed by default. Add an error-matrix row: if a persisted specific voice resolves to `localService === false`, the module must fall back to the stored gender hint or browser default and surface a non-blocking warning in Preferences. Do not rely on `navigator.onLine`; on mesh devices it is not a trustworthy proxy for internet reachability.
- **Claude-blind-spot note:** API-focused review tends to stop at "the property exists" and generic web guidance often assumes internet is intermittently available. The AREDN constraint makes this materially more severe: remote voices are not just slower, they are incompatible with the deployment model.

---

### F5.2 — ARIA treatment is incomplete; spec defines custom radio widget without required keyboard model

- **Severity:** MUST-FIX
- **Angle hit:** a11y
- **Claim in spec:** §6.1 gives `.pref-voice-buttons` `role="radiogroup"` and each button `role="radio"` with `aria-checked`; §10.3 item 11 expects VoiceOver / TalkBack to read the group correctly.
- **Issue:** This is only the surface ARIA. A custom `button role="radio"` control also needs the radio-group interaction model: a single tabbable item, arrow-key navigation between options, Space activation, and deterministic focus behavior when selection changes. None of that is specified. Without it, screen-reader and keyboard users will get three separately tabbable buttons that announce as radios but do not behave like radios. That is exactly the class of custom-widget bug native form controls avoid.
- **Proposed fix:** Replace the custom button radios with native `<input type="radio">` controls and `<label>`s, matching the existing Units/Coordinates pattern already used in the sidebar. If the visual design must stay button-like, style the labels as segmented controls and keep the real radios visually hidden but accessible. If the custom-button approach is kept, §6.1 must explicitly require roving `tabindex`, Left/Right and Up/Down arrow movement, Space selection, and focus staying on the active radio per the WAI-ARIA radio-group pattern.
- **Claude-blind-spot note:** Code/spec reviews often over-credit the presence of ARIA attributes. The missing part is behavioral parity, and that gap is easy to miss if the review is not coming from an accessibility-first angle.

---

### F5.3 — Auto-preview is hostile to screen-reader flow; speaks over assistive-tech output

- **Severity:** SHOULD-FIX
- **Angle hit:** a11y
- **Claim in spec:** §3 Q3 and §9 require auto-preview on selection; §10.3 item 11 treats accessibility as "reads as a radio group" plus correct `aria-expanded`/hidden behavior.
- **Issue:** For a VoiceOver or TalkBack user, changing the selected voice is itself an audio interaction. Immediate `speechSynthesis.speak()` on every selection means Geographica starts talking at the exact moment the screen reader is trying to announce the newly focused control, checked state, or disclosure change. The result is overlapping speech, cut-off announcements, or a user who cannot tell whether the sound came from the screen reader or the preview engine. The current a11y section checks semantics, but not the end-to-end auditory experience.
- **Proposed fix:** Change §9 so preview is explicit, not implicit, for accessible flows. Concrete text: "Selection changes update state only. A separate `Preview voice` button speaks the sample phrase. This avoids interrupting screen-reader announcements." If auto-preview must remain for sighted/touch users, require an accessibility-safe fallback: no auto-preview on focus movement, no auto-preview when selection changes via arrow-key navigation, and a live-region text confirmation that does not compete with spoken AT output.
- **Claude-blind-spot note:** Testing and concurrency reviews usually model audio as a single channel. Screen-reader UX introduces a second speech channel, and that conflict is easy to miss unless you specifically imagine VoiceOver/TalkBack operation.

---

### F5.4 — Spec says `en-*` only, but preview text and language handling are hard-coded to U.S. English

- **Severity:** SHOULD-FIX
- **Angle hit:** i18n
- **Claim in spec:** NG4 limits scope to `en-*`; §9.2 hard-codes preview text to "In 500 feet, turn right onto Main Street." / metric variant and `lang = 'en-US'`; §4.2 leaves nav utterances at `utterance.lang = 'en-US'` even when a user selects a specific `en-GB`, `en-AU`, or `en-IN` voice.
- **Issue:** "English-only" is not the same as "U.S. English only." The current spec filters in non-US English voices but then forces U.S. phrasing and language tagging anyway. That creates two problems. First, the sample phrase is culturally narrow: `Main Street` plus `turn right` plus `feet` as the default example reads as U.S.-centric even when the chosen voice is Canadian, Australian, British, or Indian English. Second, hard-coding `utterance.lang = 'en-US'` while assigning a non-US specific voice is internally inconsistent; it asks the engine to speak one locale while the chosen voice advertises another.
- **Proposed fix:** Revise §9.2 and §4.2 so `utterance.lang` follows the resolved voice when a specific voice is selected, and otherwise uses the best available English locale from the resolved voice or `en`. Replace the sample phrase with a locale-neutral line such as "Continue for 500 feet. Next turn in 500 feet." / metric equivalent, or explicitly state that the sample text is only a temporary placeholder and must not encode U.S.-specific street naming. At minimum, stop hard-coding `en-US` when the user chose `en-GB`/`en-AU`/`en-IN`.
- **Claude-blind-spot note:** Earlier rounds were aimed at API correctness and testing, which biases toward "does speech happen" rather than "does this English-only spec quietly collapse all English locales into U.S. defaults."

---

### F5.5 — UI-state story for a missing specific voice is internally inconsistent and can silently flip later

- **Severity:** MUST-FIX
- **Angle hit:** consistency
- **Claim in spec:** §7.1 step 3b says `mode: "specific"` with a missing `voiceURI` falls through to `storedGenderHint`; §8 row 2 says "On next Preferences expand, the Male / Female button reflects the fallback state"; §5.4 never rewrites storage on this fallback.
- **Issue:** The spec mixes two different concepts: persisted preference and effective resolution. If a saved specific voice disappears, the stored mode remains `specific`, but the UI is supposed to light a gender button as though the preference were now `gender`. That creates a misleading state. The user sees Female selected, but the underlying data still says "specific voice X." If that original voice reappears after `voiceschanged` or an OS change, behavior flips back to the specific voice without any user action, because storage was never normalized. The UI therefore does not truthfully represent the saved preference.
- **Proposed fix:** Pick one model and state it explicitly. Preferred option: keep the persisted mode as `specific`, keep the dropdown selection in an explicit unavailable state, and show helper text such as "Saved voice unavailable; currently falling back to Female." Do not light the gender buttons unless the module also normalizes storage to `mode: "gender"` on first fallback. If you want the UI to show Female as selected, then §7/§8 must also require rewriting localStorage from `specific` to `gender` at that point.
- **Claude-blind-spot note:** This is the kind of state-model inconsistency that gets missed when reviews focus on execution paths rather than what the UI is promising to the user over time.

---

### F5.6 — The 5-second "not supported" fallback collapses three different states

- **Severity:** SHOULD-FIX
- **Angle hit:** novel
- **Claim in spec:** §7.3 and §8 row 4 treat "`getVoices()` is still empty after 5 seconds" as equivalent to "voice selection is not supported on this browser."
- **Issue:** On Geographica's actual target devices, an empty voice list can mean at least three different things: browser truly lacks speech synthesis selection, voices have not enumerated yet, or the browser only exposes voices after a user-gesture speech prime. Those are materially different operational states, but the spec collapses them into one permanent-looking stub message. That is especially risky on offline mesh deployments because operators will interpret "not supported" as a product/platform limitation rather than a delayed-enumeration condition they can recover from.
- **Proposed fix:** Split the state machine and the user text. Add a transient "Detecting available voices..." state during bootstrap, and reserve "not supported" only for a stronger negative signal than "still empty after 5 seconds." If the list is empty but `speechSynthesis` exists, the UI should stay in a recoverable state with retry text such as "Voices not available yet on this device" plus a manual `Retry voice detection` action. The permanent unsupported stub should be the last resort, not the first timeout.
- **Claude-blind-spot note:** Browser-API and testability reviews often treat timeout-based degradation as acceptable. In an offline-first field tool, the wording of degradation matters because operators use it to decide whether the system or their environment is at fault.

---

## Non-findings appendix

- No material disagreement with the earlier Claude rounds on their core concerns after cross-checking them. The strongest overlap is the remote-voice/offline issue (independently reached via AREDN deployment constraint rather than generic Web Speech API analysis — see F5.1 vs F1.8).
- Not worth additional review energy on the spec's anti-Shrek regression test idea. Low signal, but also not the highest-risk defect class in this design.

## Summary

- **MUST-FIX (3):** F5.1 (offline/AREDN violation via cloud voices), F5.2 (a11y radio-group keyboard model missing), F5.5 (UI-state inconsistency on missing voice).
- **SHOULD-FIX (3):** F5.3 (auto-preview over screen readers), F5.4 (i18n / hard-coded en-US), F5.6 (timeout-state collapsing).

Outside-Claude value-add: F5.2 (a11y behavioral parity beyond ARIA), F5.3 (screen-reader audio-channel conflict), F5.4 (en-* ≠ en-US), F5.5 (state-model promise vs. persistence), F5.6 (degradation wording on mesh). F5.1 is high-severity overlap with F1.8 but with a sharper offline-first framing.
