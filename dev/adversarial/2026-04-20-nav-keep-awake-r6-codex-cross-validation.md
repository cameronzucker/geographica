---
round: 6
angle: Codex cross-validation (security, a11y, cross-API, AREDN, spec meta)
reviewer: codex-cli v0.118.0 (OpenAI, ChatGPT-auth)
date: 2026-04-20
---

# Round 6 — Codex cross-validation

## Findings

### F6.1 — The cumulative revision plan is internally inconsistent: R1’s bespoke-helper decision is not propagated through the spec surface
**Severity:** MUST-FIX
**Angle:** Spec META / internal consistency
**Claim / issue:** The current spec is still structurally a "NoSleep.js spec" even though the review summary says the architectural decision is now to replace NoSleep with a bespoke silent-video helper. That is not a cosmetic mismatch; it leaves acceptance criteria, test inventory, dependency section, vendoring workflow, and Appendix A all pointing at an implementation that Round 1 already invalidated. Concretely, the spec still names `frontend/vendor/nosleep.min.js` as a ship gate, still requires `window.NoSleep`, still defines failure modes around `NoSleep.enable()`, still asks for `tests/wake-lock/*.test.js` cases that assert NoSleep call counts, and still includes an appendix justifying NoSleep v0.12.0. If a subagent follows the spec as written, they will reintroduce the very dependency the prior rounds decided to remove.
**Why prior rounds missed it:** Each prior round correctly attacked one slice: R1 proved NoSleep is the wrong primitive; R2 repaired races in the canonical code; R3/R4 critiqued the still-unrevised test/dependency text; R5 stayed at product level. None of them stepped back and asked whether the post-R1 design, post-R2 race fix, and the remaining acceptance criteria can all be true at once.
**Proposed fix:** Rewrite the spec to one coherent post-review design before handoff. That means:
- Remove `frontend/vendor/nosleep.min.js`, `window.NoSleep`, and NoSleep-specific tests from §§1, 4, 5, 6, 8, 10, and Appendix A.
- Replace them with the exact first-party artifact(s) for the bespoke helper: either inline source in `frontend/wake-lock.js` or a first-party helper module plus its tiny media asset.
- Re-specify failure modes for the bespoke helper itself rather than for a third-party wrapper.
- Update acceptance criteria so a subagent cannot "pass" by shipping the rejected design.

### F6.2 — The bespoke HTTP fallback needs an explicit CSP / Permissions-Policy contract or future hardening will silently break the mainline mesh path
**Severity:** SHOULD-FIX
**Angle:** Security
**Claim / issue:** Once the design switches from NoSleep.js to a first-party silent-video helper, the security posture changes in two directions. Good news: the third-party supply-chain risk drops sharply. Bad news: the spec still treats the fallback as "just code," when in practice it depends on browser policy surfaces that are currently absent from the repo but are likely to appear later. A bespoke helper will almost certainly use either a `data:` URL, a `blob:` URL, or a local media file as the `<video src>`. Any future CSP hardening can break that path with `media-src` restrictions, and any future embedding/iframe scenario can block autoplay even if `screen-wake-lock` is irrelevant there. Today `nginx/nginx.conf` sets no CSP or Permissions-Policy headers, so the feature may work now by accident. On AREDN/HTTP, though, the fallback is not a corner case; it is the primary path. A later security hardening pass that forgets this dependency will silently regress the exact transport mode Geographica is designed to support.
**Why prior rounds missed it:** R1 focused on API correctness, not policy headers. R4 mentioned vendoring provenance and deployment but not browser enforcement surfaces. R5 looked at user-facing degradation, not future hardening risk.
**Proposed fix:** Add a short normative section for browser-policy compatibility:
- If the helper uses `blob:` or `data:` media, say so explicitly and reserve the needed CSP allowance (`media-src 'self' blob: data:` or the narrower variant that matches the chosen implementation).
- If iframe/embed mode is unsupported, say that directly in §5.15 instead of implying the fallback will rescue it.
- If embed mode is meant to work, document the required iframe permissions (`allow="autoplay; screen-wake-lock"`), because the silent-video path is also policy-gated.
- Add one regression test or checklist item: any future CSP / Permissions-Policy change must verify HTTP fallback still works.

### F6.3 — “Invisible feature” is underspecified for assistive tech: the injected `<video>` can leak into the accessibility tree
**Severity:** SHOULD-FIX
**Angle:** Accessibility
**Claim / issue:** The spec is intentionally proud of having no visible indicator, but that does not mean "no accessibility surface." A bespoke helper that lazily injects a `<video>` without explicit a11y suppression can create a ghost media element discoverable by TalkBack/VoiceOver or keyboard focus traversal. For blind or low-vision users relying on spoken navigation, an unlabeled off-screen video control is exactly the wrong failure mode: it adds noise to rotor/focus order while providing no meaningful affordance. The current spec says only that the helper should be passive and invisible; it never states that the media element must be hidden from assistive technology, non-focusable, and free of exposed controls.
**Why prior rounds missed it:** R5 discussed "no extra UI" from a product perspective, but not the DOM-level accessibility consequences of an invisible implementation detail. Earlier rounds were also reviewing the NoSleep-based design, where the implementation details of the injected element lived inside a third-party library and were easier to hand-wave.
**Proposed fix:** Specify an accessibility contract for the helper-created element:
- `aria-hidden="true"` and `tabindex="-1"`.
- No `controls`, no `title`, no accessible name, and placement outside any landmark or interactive container.
- Include a manual screen-reader acceptance step in §6.3: while nav is active, TalkBack/VoiceOver focus order should not expose an extra media control.
- If the helper leaves a dormant `<video>` in the DOM between sessions, require that it remain a11y-hidden in both active and inactive states.

### F6.4 — “Silent video” is not precise enough: the fallback asset must have no audio track, or it can collide with autoplay policy, speech priming, and microphone use
**Severity:** MUST-FIX
**Angle:** Cross-API interaction
**Claim / issue:** The post-R1 solution is described informally as a "silent-video helper." That is underspecified in a dangerous way. Browsers treat "muted video" and "video file with no audio track" differently in edge cases. If the helper ships a tiny MP4/WebM that still contains an audio track with silence, the autoplay rules and media-session behavior are materially less predictable: some browsers classify it as audible media unless muted at the right moment, some lock-screen/UIs surface it as a media session, and it has a much higher chance of interacting badly with the two other media-ish systems active here: `speechSynthesis` priming in `startNavigation()` and `getUserMedia` / `AudioContext` when STT is active over HTTPS. On iPhone-in-vehicle use, that can show up as the wrong thing owning the media session or the fallback requiring stricter activation than the spec assumes.
**Why prior rounds missed it:** R1 correctly recommended "replace NoSleep with a bespoke silent-video helper," but stopped at architectural choice, not media-file semantics. R2 and R3 stayed in state-machine and test territory. No prior round checked the exact contract the replacement helper must satisfy to coexist with Geographica's already-active speech and mic APIs.
**Proposed fix:** Make the helper media contract explicit:
- The asset must contain **no audio track at all**, not merely a silent track.
- The element must be created with `muted`, `playsInline`, `loop`, and no controls.
- Add `disablePictureInPicture` and `disableRemotePlayback` to reduce accidental media-UI exposure on mobile/vehicle environments.
- Add one manual acceptance item: with nav voice enabled, start nav, confirm spoken prompts still fire normally while fallback video is active; with STT enabled on HTTPS, verify starting/stopping voice search still works.

