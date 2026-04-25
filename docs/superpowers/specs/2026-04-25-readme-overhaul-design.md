# README overhaul — design

**Status:** Spec  
**Date:** 2026-04-25  
**Agent:** tinaja  
**Topic:** Refactor the 838-line monolithic `README.md` into a multi-document structure suitable for showing the project to senior technical and executive audiences as a working example of AI-orchestrated development on a constrained budget.

---

## 1. Goal

Replace the current functional-but-flat `README.md` with a multi-document set that:

1. Stops asking the reader to skim 838 lines to find what they came for.
2. Tells the dual story — *what Geographica does* and *how it was built* — without compromising either.
3. Provides linkable, first-class artifacts (process page, cost methodology) suitable for use in CV / talks / interview decks / Hacker News submissions.
4. Survives skeptical reading by senior engineers, executive non-engineers, technical peers, and prospective users — all in the same document.

**Non-goal:** This is not a feature change, codebase refactor, or testing improvement. The artifact is documentation. The shipped software is not affected.

---

## 2. Audience

Designed for four reader types in parallel, served via **progressive disclosure** (each tier reads top-to-bottom and bails when satisfied):

| Tier | Reader | Bails after |
|---|---|---|
| 1 | **Executives / non-engineering decision-makers** | Hero shot + meta-callout (first viewport) |
| 2 | **Technical peers / hiring-manager class / HN reader** | Features + architecture diagram |
| 3 | **Engineering leadership at the user's employer** | Hardware + project layout + further-reading hub |
| 4 | **Actual potential users (AREDN ops, ham radio, field teams)** | Continues into `SETUP.md` / `MANUAL_SETUP.md` |

**Primary audience driving design conflicts:** the mix is genuinely all-four; progressive disclosure resolves the conflict structurally rather than picking a winner.

---

## 3. Constraints

- GitHub-flavored markdown rendering only. Limited inline HTML. Mermaid diagrams supported natively (since 2022).
- No build step for documentation.
- No new third-party dependencies for asset generation beyond what is already in the repo or installable via `pip` / `apt`.
- All cost claims must be reproducible from on-disk data; no unverifiable numbers.
- Voice rules from `feedback_writing_voice_no_first_person.md` apply: declarative, no first-person, even for narrative sections.

---

## 4. Locked design decisions

Eight decisions resolved during the 2026-04-25 brainstorm. Listed here as the canonical source so the implementation plan can reference them without re-litigation.

### 4.1 Hero treatment — Artifact-first

The README opens as a real product (artifact-first). The meta-story ("built by an AI agent team in 19 days") sits in a callout *below* the hero screenshot, not in the headline. Audience D (real users) sees a working product, not a tech demo. Audience B (executives) still sees the meta-story before bouncing.

### 4.2 Cost framing — Prose-led, no hardware dollar figure

The "How it was built" callout is one paragraph of prose (not a stat strip). Cost: "**~$2,500 of API-equivalent model output**, paid as a Claude Max subscription (~$200/mo)." Hardware dollar figures are omitted (they age poorly; "Pi 5" already reads cheap by reputation). Two trailing inline links: `Read the process →` · `Cost methodology →`.

### 4.3 Cost methodology — Honest two-number disclosure

The full $21,858 list-price number is **not** in the README. It lives in `docs/COST_METHODOLOGY.md` with full reasoning: cache reads dominate the list price, cache reads are a harness artifact (not work), the $2,489 number is the honest "model work" measure that any reader can reproduce with `ccusage` or the included audit script. No lie of omission, but the headline is the meaningful number.

### 4.4 Tone — Declarative, no first-person

Per `feedback_writing_voice_no_first_person.md`. Project-voice / implicit-author throughout — no `I`, no `we`. Applies to all five docs in this overhaul.

### 4.5 Screenshots — Tiered shot list

| Tier | Count | Shots |
|---|---|---|
| Hero | 1 | Map + NAIP imagery + GPS pin + active turn-by-turn route + maneuver banner |
| Inline (in README, beside features) | 5 | 3D terrain · voice search · public lands · admin pipelines · mobile/in-vehicle nav |
| Gallery (in `MANUAL_SETUP.md` or `SETUP.md`) | 3 | Setup wizard · KMZ overlay · imagery before/after |
| Skip | 1 | ATAK integration (mention as bullet only) |

### 4.6 Doc split — 5 files (T2)

| File | Status | Purpose |
|---|---|---|
| `README.md` | rewrite | Overview, features, screenshots, meta-callout, getting-started pointer |
| `docs/SETUP.md` | new | Wizard happy path, ~150 lines |
| `docs/MANUAL_SETUP.md` | new (extracted from current README §"Manual setup") | Advanced/recovery/AI-agent reference, ~500 lines |
| `docs/PROCESS.md` | new | The meta-story as a first-class linkable artifact, ~250 lines |
| `docs/COST_METHODOLOGY.md` | new | Cost audit + reproduction, ~120 lines |

### 4.7 Visual identity

| Axis | Choice |
|---|---|
| Header | Existing `docs/geographica_favicon.png` as a 64–80 px inline image left of `# Geographica` + one-line tagline |
| Badges | Standard set (license · version · CI · python) plus two custom shields.io badges (`built in: 19 days`, `agents: 17`) |
| Architecture diagram | Mermaid flowchart (replaces current ASCII) |
| Screenshot framing | Subtle border + drop shadow for desktop shots; phone frame for mobile shots. **Both must be baked into the PNG asset** (GitHub markdown ignores CSS); use Playwright post-processing or an image library like Pillow for desktop framing, and a service like mockuphone.com or a transparent phone-frame PNG composited via Pillow for mobile shots |
| OG / social-share image | Custom 1200×630 image, configured via repo Settings → Social preview |

### 4.8 Screenshot capture method — Mixed (Playwright + manual)

Playwright (already installed in `dev/harness/`) drives capture for any shot that doesn't require live GPS or in-vehicle context: 3D terrain, voice search, public lands, admin pipelines, setup wizard, KMZ overlay, imagery before/after. The user (Cameron) captures the GPS-pinned hero shot and the mobile-in-vehicle shot from a phone. If Playwright output quality is insufficient, fall back to manual capture for any subset; only screenshots are at stake.

---

## 5. README outline (the 11 sections)

| # | Section | Tier audience | Lines |
|---|---|---|---|
| 1 | Header — favicon + wordmark + badge row | Exec | ~10 |
| 2 | One-paragraph elaboration | Exec | ~5 |
| 3 | Hero screenshot ("the everything shot") | Exec | ~3 |
| 4 | "How it was built" callout (with cost prose + 2 links) | Exec | ~8 |
| 5 | Features — 4 thematic groups, each with 1 inline screenshot | Peer | ~70 |
| 6 | Architecture — Mermaid diagram + 2-paragraph caption | Peer | ~30 |
| 7 | Hardware requirements — min/recommended + storage budget tables | Leadership | ~25 |
| 8 | Get started — 4-line wizard quick-start + links to SETUP / MANUAL_SETUP | User | ~15 |
| 9 | Project layout — compact ASCII tree | User | ~25 |
| 10 | Further reading — indexed sibling-doc list | User | ~15 |
| 11 | License | User | ~3 |

**Estimated total: ~210 lines** (down from 838).

**Cut from README** (moves to sibling docs or removed): inline manual setup walkthrough, stack management commands, troubleshooting, customizing coverage, ports reference, TLS deprecation banner (already in `UPGRADING.md`), inline companion-utility paragraph (moves to `PROCESS.md`).

### 5.1 Feature groupings

Section 5 organizes the existing 20+ feature bullets into 4 thematic groups. Each group gets one inline screenshot.

| Group | Screenshot | Bullets |
|---|---|---|
| **Mapping & imagery** | Public lands shot | Vector basemaps · aerial imagery (5 modes) · public lands · 3D terrain · hillshade · imperial/metric units · coordinate display |
| **Spatial intelligence** | Voice search shot | Natural-language search · voice search · OSM POI · geocoding · POI search |
| **Navigation & GPS** | Mobile-nav shot | Turn-by-turn nav · multi-stop routing · live GPS · KML/KMZ import · print/export directions |
| **Operations & admin** | Admin-pipeline shot | Admin config panel · pipeline management · ATAK integration · TLS support · credential security · no build step |

3D terrain shot anchors the section open as the "complete GIS stack" punctuation.

---

## 6. Sibling docs

### 6.1 `docs/SETUP.md` (~150 lines, audience D)

The 95% happy path. Reader goes from "fresh Pi" to "working stack" in under 30 minutes.

| # | Section | Notes |
|---|---|---|
| 1 | Before you start | hardware + storage + network checklist |
| 2 | Bootstrap | the `bootstrap.sh` step (sudo prerequisites) |
| 3 | Run the wizard | screenshot of each of the 5 wizard steps with annotated decisions (gallery-tier wizard shot lives here) |
| 4 | Verify | three quick checks confirming the stack is healthy |
| 5 | Common issues | the 4-5 most-asked beta-tester questions, with fixes |
| 6 | When you outgrow this | pointer to `MANUAL_SETUP.md` for advanced cases |

### 6.2 `docs/MANUAL_SETUP.md` (~500 lines, audience D advanced + AI agents)

Sections 1-12 of the current README's "Manual setup" section, lifted nearly verbatim. Plus migrated sections (stack management, troubleshooting, customizing coverage, ports reference). Existing structure already battle-tested; minimal restructuring.

### 6.3 `docs/PROCESS.md` (~250 lines, audiences A + C)

The meta-story as a first-class linkable artifact.

| # | Section | Notes |
|---|---|---|
| 1 | What was built, in numbers | 19 days, 932 commits, 17 named agents, 41 specs, 104 test files, 7 services, ~$2.5K inference |
| 2 | The workflow | brainstorm → adversarial spec review → TDD execution by parallel sub-agents (one full feature walked through end-to-end as worked example) |
| 3 | Adversarial review patterns | multi-model rounds (Sonnet, Opus, Codex); what each model is good at finding; the "Codex catches what 4 Claudes miss" pattern with a concrete example |
| 4 | Subagent orchestration | agent monikers, branch hygiene, lessons from the 2026-04 worktree-escape incidents (link out to the recovery write-up in `docs/pitfalls/implementation-pitfalls.md` §14–15 rather than re-narrating in this doc) |
| 5 | What this enables (and what it doesn't) | honest read on what works (full-cycle features under good specs) and what doesn't (visual polish, ambiguous specs, anything benefiting from human aesthetic judgment) |
| 6 | Companion utility | the cross-platform desktop tool moves here as a process artifact |
| 7 | References | links to `docs/superpowers/specs/`, `dev/implementation-log.md`, `CHANGELOG.md` as the receipts |

### 6.4 `docs/COST_METHODOLOGY.md` (~120 lines, audience C)

Sketched in the brainstorm. Honest audit of the cost number.

| # | Section | Notes |
|---|---|---|
| 1 | Headline number ($2,489) | API-equivalent model output (uncached input × $15/M + output × $75/M for Opus, proportional rates for Sonnet/Haiku); matches what `ccusage` reports |
| 2 | Full list-price number ($21,858) | Headline + cache-read tokens (8.1 B at $1.50/M = $12.1K) + cache-write tokens (110 M at $18.75–$30/M = $3.3K); explains cache reads are a harness artifact |
| 3 | What was actually paid | Claude Max subscription, ~$200/mo for one month; Pi 5 hardware (per repo README hardware section) |
| 4 | Why two numbers, not one | Both are honest; they answer different questions; explicit framing |
| 5 | Reproduction | invocation of `scripts/audit_inference_cost.py` with sample output; reader can verify on their own `~/.claude/projects/*/` |

---

## 7. Asset and script deliverables

| Deliverable | Path | Complexity |
|---|---|---|
| Audit script | `scripts/audit_inference_cost.py` | low (already prototyped during brainstorm) |
| Custom OG image | `docs/og-image.png` (1200×630) | medium (needs design pass) |
| Header banner | `docs/geographica_favicon.png` (existing) | low (no new asset) |
| Hero + 5 inline screenshots | `docs/screenshots/*.png` | high (coordinated capture session) |
| 3 gallery screenshots | `docs/screenshots/gallery/*.png` | medium (same stack, less precision) |
| Mermaid architecture diagram | embedded in `README.md` | low (direct translation of current ASCII) |
| Custom badges | inline in `README.md` badge row | low (shields.io URL-only) |
| Cross-link audit | manual checklist or `scripts/audit_doc_links.sh` | low (one-time grep) |

---

## 8. Out of scope

- Changes to `CHANGELOG.md`, `CONTRIBUTING.md`, `VERSIONING.md`, `UPGRADING.md`, `LICENSE`, `AGENTS.md`, `CLAUDE.md`. These already exist and are not part of the overhaul.
- Translating any documentation to non-English locales.
- Restructuring `dev/` or other internal/working directories.
- Changes to wizard UI, admin panel, or any frontend asset.
- Marketing site, GitHub Pages site, or any external-hosted documentation.
- Press release, blog post, or talk submission. (Those may *consume* `PROCESS.md` and `COST_METHODOLOGY.md` later, but are not part of this overhaul.)

---

## 9. Open questions / risks

### 9.1 Screenshot quality is the highest single risk

If the Playwright-captured shots look amateurish or fail to convey what they need to (e.g., 3D terrain doesn't read as 3D in a still frame; voice search needs a moment-in-time UI that's hard to script), the README's audience-B and audience-C impact drops sharply. **Mitigation:** Mixed capture method (decision 4.8) + explicit fallback to manual capture if Playwright output is poor; only screenshots are at stake, not the spec.

### 9.2 The two-cost-number framing may still confuse skeptical readers

Some peers will read "~$2.5K" in the README, click through to `COST_METHODOLOGY.md`, see "$22K", and conclude the README is misleading. **Mitigation:** the methodology page leads with the headline number being the honest one and cache reads being overhead — but the framing depends on the reader trusting the explanation. **Acceptance:** this is the cost of being honest; the alternative (omitting the $22K) would be worse.

### 9.3 `MANUAL_SETUP.md` carries forward existing rough edges

The current "Manual setup" section was written incrementally and may have stale steps, broken commands, or sections that no longer match the codebase. **Decision:** lift nearly verbatim for this overhaul; flag any obvious staleness during migration but do not perform a full audit. A separate rewrite of `MANUAL_SETUP.md` is its own task.

### 9.4 `PROCESS.md` has no precedent in the repo

This is a first-of-its-kind document for the project. The "What this enables (and what it doesn't)" section in particular is at risk of either (a) reading as boastful, or (b) reading as defeatist. **Mitigation:** worked-example walkthrough in §2 grounds the abstract claims in a concrete shipped feature; the "what it doesn't" section is not optional.

### 9.5 Voice rule may collide with the natural register of `PROCESS.md`

`PROCESS.md` is the most narrative document in the set. The no-first-person rule (decision 4.4) may produce slightly stilted prose ("The agent team built the feature in three days" instead of "I worked with agents to build it in three days"). **Decision:** the voice rule wins. Stilted prose is preferable to first-person leakage; if a sentence resists declarative framing, restructure rather than concede.

---

## 10. Definition of done

- [ ] `README.md` is ~210 lines, organized into the 11 sections in §5.
- [ ] All four sibling docs exist at the paths in §6 and follow the section structures listed.
- [ ] All eight asset / script deliverables in §7 are in place and referenced from the docs.
- [ ] Voice rule (no first-person) holds across all five docs.
- [ ] Every relative link in the doc set resolves (no 404s).
- [ ] All screenshots are captured, post-processed (border + shadow / phone frame), and committed.
- [ ] Mermaid diagram renders correctly on `github.com/<repo>/blob/dev/README.md`.
- [ ] Custom OG image is configured via repo Settings → Social preview and verified by sharing the repo URL into a Slack-class preview tool.
- [ ] `scripts/audit_inference_cost.py` runs cleanly against an arbitrary `~/.claude/projects/*/` directory and reproduces the numbers in `COST_METHODOLOGY.md` ±1%.
- [ ] Cameron has read all five docs end-to-end and approved publication.

---

## 11. Sequencing notes (for the implementation plan)

The implementation plan (next skill, `writing-plans`) will sequence these deliverables. Suggested ordering principle: **content-first, assets-second.** Concretely:

1. Audit script and cost methodology page first — proves the cost numbers, unblocks the README callout.
2. New README.md skeleton (sections, prose, no screenshots yet) — establishes the structure to which everything else attaches.
3. `MANUAL_SETUP.md` and `SETUP.md` — extraction work, lower creative load.
4. `PROCESS.md` — the most novel document; benefits from being written after the structural pieces are in place.
5. Mermaid diagram, custom badges, header treatment — cosmetic, can land in parallel.
6. Screenshot capture (Playwright + manual) — last, because the README structure must be settled before knowing the exact frame each shot fills.
7. OG image — last, because it composites a final hero screenshot.
8. Cross-link audit and verification — gate before shipping.
