# Gas City 1.0.0 — Assessment for Geographica multi-agent coordination

**Researched by:** agent `pinyon-research-gascity`
**Date:** 2026-04-24
**For:** Cameron Zucker — does Gas City solve the parallel-agent coordination
problems we're hitting in our current Claude Code workflow?

---

## 1. What Gas City is

Gas City is an **MIT-licensed, open-source, self-hosted SDK for building
multi-agent coding orchestrations**. It shipped v1.0.0 today (2026-04-24).

- **Built by:** Julian Knutsen and Chris Sells, in the orbit of Steve Yegge's
  "Gas Town" / "Gaslandia" project family. Yegge writes about it but did not
  author the code; he calls it "exactly what I wished for."
- **Predecessor:** Gas Town (1.0.0 shipped 2026-04-03) — a fixed-topology
  multi-agent harness with named roles (mayor, deacon, witness, refinery,
  polecat, crew, dog). Gas City is Gas Town **decomposed into reusable
  primitives** — agents, beads, events, config, prompt templates, orders,
  formulas, waits, mail, sling — that you assemble into your own topology.
- **Distribution:** Go binary `gc`, installed via `brew install gastownhall/gascity/gascity` or `make install` from the repo. Requires `tmux`, `git`, `jq`, `pgrep`, `lsof`, and (for the default `bd` beads backend) `dolt` >= 1.86.1 and the `bd` CLI.
- **Storage substrate:** **Dolt** — a git-versioned SQL database — backs the
  "MEOW stack" (Molecular Expression of Work). Every agent action, every work
  item ("bead"), every state change is committed to a versioned ledger.
- **Runtime providers:** tmux, subprocess, exec, ACP, and Kubernetes. So
  agents can run as tmux sessions on the host, as plain subprocesses, or
  across a K8s cluster.
- **Coding-agent providers (the things that actually call models):** Claude
  Code, Codex CLI, Gemini CLI, Cursor Agent, GitHub Copilot, Sourcegraph
  AMP, OpenCode, Auggie CLI, Pi Coding Agent, Oh My Pi, plus a "Custom
  command" escape hatch. **Not provider-locked.**
- **Mental model:** A **city** is a working folder containing one
  orchestration environment. A **pack** is the portable, reusable definition
  of a city's behavior (`pack.toml`). A **rig** is a project directory
  registered to the city — the actual code an agent operates on. **Agents**
  are generic workers; their roles come from prompts, formulas, and orders,
  not from baked-in SDK types. Work items are **beads** — git-versioned
  records linked into a queryable knowledge graph. Recurring workflows are
  **formulas** (templates) instantiated as **molecules** (deterministic step
  sequences a crew executes).

---

## 2. The 8-question assessment

| # | Question | Verdict | Evidence (1-sentence) |
|---|---|---|---|
| 1 | Branch / worktree state isolation per agent | **YES (opt-in, explicit)** | Each agent has a `work_dir` field; the canonical idiom for repo-mutating agents is `work_dir = ".gc/worktrees/<rig>/crew/<agent>"`, and a dedicated `pre_start` hook can call `git worktree add` so the agent gets its own checkout (`coming-from-gastown.md` lines 157–164, 304–308, 522–525). |
| 2 | Handoff coordination | **YES** | `gc handoff` is a first-class command (mapped 1:1 from `gt handoff`), and durable handoff state lives in bead metadata so the receiving agent picks up shared context without manual reconciliation. |
| 3 | Multi-agent parallelism on a shared codebase | **YES** | A controller/supervisor loop reconciles desired vs. running session state across **hundreds** of concurrent workers (Yegge: "Julian has had hundreds of concurrent workers in a city"; the launch post claims a 40 → 600 parallel-agent jump from Gas Town to Gas City); per-agent `work_dir` + worktrees prevents stepping on shared files. |
| 4 | Audit trail | **YES (this is the headline feature)** | Every agent action becomes a bead committed to a Dolt git-versioned database; `gc events`, `gc graph`, and `bd` queries replay the full history. Yegge: "the forensics and auditing capabilities of Gas City are unparalleled." This directly answers the "which agent did this commit" pain. |
| 5 | Plan-driven execution with review checkpoints | **PARTIAL → YES** | **Formulas** are reusable templates for units of work; **molecules** are concrete instantiations with deterministic steps; **convergence loops** provide bounded iterative refinement; **waits** gate execution on dependencies. This is structurally similar to our `writing-plans` → `subagent-driven-development` pattern but the *adversarial-review discipline itself* is something you'd encode as a formula, not something Gas City ships out of the box. |
| 6 | Cross-model orchestration (Claude + Codex + others) | **YES** | The init wizard explicitly lists 10 named providers (Claude Code, Codex, Gemini, Cursor, Copilot, AMP, OpenCode, Auggie, Pi, OMP) plus a custom-command slot; per-agent `provider = "codex"` overrides let one pack mix models. Yegge stresses fine-grained model selection at multiple levels for cost control. |
| 7 | Self-hostable / runs locally | **YES (local-first by design)** | MIT-licensed binary, runs on macOS and Linux, defaults to local tmux sessions; the only network dependencies are whichever provider APIs your agents call. Optional cloud hosting exists but is opt-in. **Fits Geographica's offline-first ethos.** |
| 8 | Cost model | **FREE for the orchestrator; pay-for-tokens at the model layer** | Gas City itself is open-source MIT and self-hosted (no per-seat fee, no per-agent-hour fee); spend is whatever your underlying providers charge — same model as Claude Code's "use your own API key." Net cost vs. Claude Code is roughly neutral plus the ops overhead of running Dolt + tmux + the supervisor. |

---

## 3. Bottom line

**Gas City directly addresses the acute pain that motivated this research.**
The "wrong-branch commit" problem is a *symptom* of two missing primitives in
Claude Code's subagent model: per-agent filesystem isolation and a
cross-session audit ledger. Gas City has both — `work_dir` + worktree
isolation per agent, and a Dolt-versioned ledger that records every action by
every agent — and it explicitly supports running Claude Code, Codex, and
others as interchangeable providers, which preserves the adversarial-review
pattern (`superpowers:build-robust-features`) we already rely on.

**Tradeoffs and caveats:**

1. **Operational footprint.** Gas City requires running a supervisor daemon,
   Dolt, tmux, and the `bd` CLI continuously. That's a meaningful step up
   from "open Claude Code in a terminal." For Geographica (a single-developer
   project on a Pi), this is real overhead; Cameron would be paying ops cost
   to solve a coordination problem that Cameron alone is currently hitting.
2. **Maturity is fresh.** v1.0.0 shipped *today*. Gas Town's own 1.0
   retrospective frankly describes a "wild 3-month ride" of "serial killer
   sprees" and "data loss." Gas City is positioned as more disciplined and
   benefits from inheriting Dolt-backed Beads, but expect rough edges in
   month one. The wisdom move is to track it for ~30–60 days while the
   community shakes out v1.x bugs.
3. **Mental model investment.** "Cities, packs, rigs, beads, molecules,
   formulas, orders, convoys, polecats" is not a small vocabulary. Cameron's
   `superpowers` discipline (brainstorm → adversarial → plan → execute) is
   already producing good outcomes; switching to Gas City means re-encoding
   that discipline as Gas City formulas + orders. There's a real one-time
   cost.
4. **Geographica isn't its sweet spot.** Yegge's pitch is enterprise
   "de-SaaSing" and dark factories that replace seven-figure tooling spend.
   For a personal learning sandbox + small offline GIS deployment, you'd be
   adopting an enterprise orchestration plane to solve a single-developer
   coordination friction. Worth it only if you also intend to use it for the
   work-project AI techniques Cameron is upskilling for.

**Recommendation, in one paragraph:** Gas City *is* the kind of tool Cameron
described needing — it solves the audit-trail and isolation gaps that bit us,
keeps Claude as a first-class provider, and is MIT/local-first in a way
Geographica's ethos can absorb. But the operational footprint and concept
overhead are non-trivial, and v1.0.0 is one day old. Best path forward:
**install it on the Pi as an experiment in a separate workspace** (not on the
Geographica repo yet), run a few non-critical orchestrations (e.g.
`build-robust-features` re-encoded as a Gas City formula) for two weeks, and
re-evaluate once the v1.x bug-fix wave settles. The high-value transferable
skill — multi-agent orchestration with strong audit — is exactly the kind of
"professional-development outcome" the project ethos prioritizes, so the
learning investment lines up with the broader Geographica goals even if
Geographica itself never adopts it as the primary harness.

---

## 4. Sources

### Primary launch / vision posts
- [Welcome to Gas City — Steve Yegge, 2026-04-24 (launch announcement)](https://steve-yegge.medium.com/welcome-to-gas-city-57f564bb3607)
  → `/tmp/2026-04-24-welcome-to-gas-city.md`
- [Gas Town: from Clown Show to v1.0 — Steve Yegge, 2026-04-03 (predecessor retrospective)](https://steve-yegge.medium.com/gas-town-from-clown-show-to-v1-0-c239d9a407ec)
  → `/tmp/2026-04-03-gas-town-from-clown-show-to-v1-0.md`

### Project hub
- [Gas City Hall — official hub (Chris Sells)](https://gascityhall.com/)
  → `/tmp/2026-04-24-gas-city-hall.md`

### Code and docs
- [GitHub — gastownhall/gascity (repo README)](https://github.com/gastownhall/gascity)
  → `/tmp/2026-02-22-github-gastownhall-gascity-orchestration-builder-sdk-for-multi-agent-coding-work.md`
- [Tutorial 01 — Cities and Rigs (quickstart walkthrough)](https://github.com/gastownhall/gascity/blob/main/docs/tutorials/01-cities-and-rigs.md)
  → `/tmp/2026-02-22-gascity-docs-tutorials-01-cities-and-rigs-md-at-main-gastownhall-gascity.md`
- [Coming from Gas Town (concept-mapping doc — primary source for `work_dir`/worktree behavior)](https://github.com/gastownhall/gascity/blob/main/docs/getting-started/coming-from-gastown.md)
  → `/tmp/2026-02-22-gascity-docs-getting-started-coming-from-gastown-md-at-main-gastownhall-gascity.md`

### Community
- Discord: [gastownhall.ai](https://gastownhall.ai/) (~2000+ members per the launch post)
