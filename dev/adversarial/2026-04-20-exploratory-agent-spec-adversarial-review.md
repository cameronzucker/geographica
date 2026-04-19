# Adversarial Review — Exploratory-Agent Beta-Tester Harness Spec

**Spec:** `docs/superpowers/specs/2026-04-20-exploratory-agent-harness-design.md`
**Plan:** `docs/superpowers/plans/2026-04-20-exploratory-agent-harness.md`
**Date:** 2026-04-20
**Reviewer:** Claude Opus 4.7 (adversarial critique of own spec)
**Rounds:** 4 personas — feasibility, cost + reliability, security, evaluation quality.

---

## Round 1 — Feasibility

**Persona:** Engineer picking up this plan cold and implementing Task 1 through 10 without having written the spec.

### 1.1 CRITICAL — `asyncio.get_event_loop()` in sync shims is broken on Python 3.13

**Location:** `dev/harness/exploratory_agent/tools/browser.py`, `_sync` methods.

**Problem:** Python 3.13 deprecated `asyncio.get_event_loop()` when no loop is running. It now raises a DeprecationWarning in 3.13 and will raise RuntimeError in 3.14. The plan's sync shims rely on `asyncio.get_event_loop().run_until_complete(...)`. Inside pytest, no loop is running, so the call creates a new loop every time — but the agent loop in `__main__.py` explicitly creates + sets a loop via `asyncio.set_event_loop(loop)`. If the sync shims use `get_event_loop()` they'll pick up the already-set loop, but the BrowserTools methods are declared `async` and awaited from tests via a different mechanism.

Concretely: the unit tests `test_page_goto_returns_status_and_final_url` and `test_page_body_text_is_truncated_at_16kb` will likely fail in pytest because:
1. Pytest doesn't set an event loop by default.
2. `get_event_loop()` in 3.13 without a running loop emits a DeprecationWarning and returns a loop that's unusable for `run_until_complete` in some edge cases.

**Fix:** The sync shims must NOT rely on `get_event_loop()`. Either:
- Drop the `_sync` methods entirely and test the `async` methods via `pytest.mark.asyncio`.
- OR create + close a fresh loop inside each `_sync` method (slow, correct):
  ```
  loop = asyncio.new_event_loop()
  try:
      return loop.run_until_complete(self.page_goto(url))
  finally:
      loop.close()
  ```

Add this to Task 2 Step 4. Also change the unit tests to use `pytest.mark.asyncio` + `AsyncMock` directly on `page_goto` (async method), not `page_goto_sync`.

**Severity:** Critical. Task 2 won't pass `pytest` as written.

---

### 1.2 HIGH — Agent-loop handler signature mismatch

**Location:** `agent_loop.py::run_session`, the `handler(**block.input)` call.

**Problem:** `handler` is the result of `factory(ctx)`. Most factories return a method handle like `ctx.browser.page_goto_sync` which expects `(url,)`. But `ctx.control.describe_wizard_state_sync` takes NO arguments, and `ctx.reporting.report_finding_sync` takes ONLY keyword-only arguments (`classification=..., severity=..., ...`). If the agent happens to call `page_goto` with `{"url": "x", "extra": "y"}` (an off-spec key), `**block.input` raises TypeError because `page_goto` doesn't accept `extra`.

The spec says tools must validate their inputs against their schema — but the plan skips the schema validation layer entirely. It just `**unpacks` the agent's input into the handler.

**Fix:** Either (a) add a `jsonschema.validate(block.input, schema["input_schema"])` call before dispatch in `agent_loop.run_session`, trapping `jsonschema.ValidationError` as a `tool_result` error back to the model, OR (b) make every handler accept `**_unused` kwargs and return a clear `{"ok": false, "error": "..."}` on bad input. (a) is cleaner and catches issues at the schema layer; (b) is more permissive and more agent-friendly.

Recommend (a). Add `jsonschema>=4.0` to `requirements.txt` (Task 1 Step 2) and wire validation in the loop (Task 7 Step 3).

**Severity:** High. Will bite the first time the agent calls a tool with an extra kwarg, which Claude does regularly.

---

### 1.3 HIGH — `describe_wizard_state` implementation is a placeholder

**Location:** `tools/control.py::ControlTools.describe_wizard_state_sync`.

**Problem:** Task 5 Step 3 has the implementation return a stub with `"note": "describe_wizard_state orchestration wired in agent_loop.py"`. But Task 7 doesn't wire it either. The tool gets registered with a schema; the agent will call it; it will always return the stub. That's a latent "this tool is a lie" trap.

**Fix:** In Task 5 Step 3, implement `describe_wizard_state_sync` for real. Use a dedicated event loop (same pattern as the other sync shims per Issue 1.1). The method needs to call:
- `page.inner_text("body")` — to count tracebacks
- `page.is_visible("#global-error-banner")` + `page.inner_text(...)` — for banners
- `page.query_selector_all(".preflight-dot")` + iterate class attrs — for preflight status
- `page.inner_text("#btn-next")` + `page.get_attribute("#btn-next", "disabled")` — for button state
- `page.query_selector_all("[id^=step-]")` + find the one with `display != none` — for current step

Sketch of the async implementation (agent adapter):
```
async def describe_wizard_state_real(page):
    out = {"visible_error_banners": [], "preflight_dots": []}
    banner = page.locator("#global-error-banner")
    if await banner.count() > 0 and await banner.is_visible():
        out["visible_error_banners"].append(await banner.inner_text())
    # preflight
    dots = page.locator(".preflight-dot")
    for i in range(await dots.count()):
        d = dots.nth(i)
        cls = await d.get_attribute("class") or ""
        status = next((c for c in cls.split() if c in ("ok", "error", "warning", "missing", "checking")), "unknown")
        item = d.locator("xpath=ancestor::div[contains(@class,'preflight-item')][1]")
        name = (await item.locator(".preflight-name").inner_text()).strip()
        out["preflight_dots"].append({"name": name, "status": status})
    # btn-next
    btn = page.locator("#btn-next")
    if await btn.count() > 0:
        out["btn_next_text"] = (await btn.inner_text()).strip()
        out["btn_next_disabled"] = (await btn.get_attribute("disabled")) is not None
    # step
    for i in range(1, 6):
        el = page.locator(f"#step-{i}")
        if await el.count() and await el.is_visible():
            out["step"] = i
            break
    else:
        out["step"] = None
    return out
```

The sync shim: `asyncio.new_event_loop().run_until_complete(describe_wizard_state_real(self.browser.page))`. Task 5 Step 3 must include this.

**Severity:** High. The agent relies on this tool; a stub return makes the session useless.

---

### 1.4 MEDIUM — Test fixtures rely on `MagicMock` return values that `json.dumps` can't handle

**Location:** `test_agent_loop_auto_stops_at_max_turns`.

**Problem:** The mocked `resp` is a MagicMock; `resp.content` is a list of MagicMock (type="text", text="thinking..."). The loop does `json.dumps(result, default=str, ...)` when writing tool results. But also logs the `assistant_text` event with `block.text[:500]`, which is fine because it's a string. The issue: `resp.usage.input_tokens` is a MagicMock, not an int — the transcript log does `{"usage": {"input": getattr(resp.usage, "input_tokens", 0), ...}}`. The MagicMock doesn't JSON-serialize cleanly; `default=str` saves us but produces ugly output.

**Fix:** In the tests, configure MagicMock with `spec=` or directly: `usage=MagicMock(input_tokens=1, output_tokens=1)` with int attributes. Already done in the test — actually this is fine. Downgrading to cosmetic.

**Severity:** Medium → Cosmetic on re-read.

---

### 1.5 MEDIUM — `container_restart_wizard` assumes unit name `geographica-wizard-setup.service`

**Location:** `tools/container.py::container_restart_wizard_sync`.

**Problem:** The unit name is hardcoded. It matches what `wizard-ci.sh` uses (`systemd-run --unit=geographica-wizard-setup`) — verified. But if someone later renames the unit in wizard-ci.sh, the agent silently breaks. There's no test linking them.

**Fix:** Add to Task 4 Step 1 a test that reads `wizard-ci.sh` and greps for the `--unit=` value, then asserts it matches the hardcoded name in `container.py`:

```
def test_container_restart_unit_name_matches_wizard_ci_sh():
    from pathlib import Path
    ci_sh = (Path(__file__).parent.parent / "dev" / "harness" / "wizard-ci.sh").read_text()
    m = re.search(r"--unit=(\S+)", ci_sh)
    assert m, "wizard-ci.sh no longer uses systemd-run --unit=..."
    from dev.harness.exploratory_agent.tools.container import ContainerTools
    # Introspect the source; ContainerTools has the name hardcoded.
    import inspect
    src = inspect.getsource(ContainerTools.container_restart_wizard_sync)
    assert m.group(1) in src, \
        f"wizard-ci.sh uses unit {m.group(1)!r}; ContainerTools does not reference it"
```

Lift the unit name into a module constant first so the introspection is reliable:
```
WIZARD_SYSTEMD_UNIT = "geographica-wizard-setup.service"
```

**Severity:** Medium. Soft-coupling bug waiting to happen.

---

## Round 2 — Cost + reliability

**Persona:** A finance-minded ops lead reviewing the cost envelope + debugging experience.

### 2.1 HIGH — No per-run token budget; runaway agent could cost materially more than \$5

**Location:** Spec §Architecture (claims ~\$2-5/run at 15 min) and `agent_loop.run_session`.

**Problem:** The spec states the budget envelope but the loop has no token-count breaker. The only terminators are `max_turns`, `deadline_epoch`, and the agent calling `stop`. An agent that calls 200 tools each returning 16 KB of body text could blow past \$5/run. Claude Sonnet 4.6 pricing is ~\$3/M input + \$15/M output. At 16 KB × 200 = 3.2 MB of input text accumulated across the history, that's ~\$10 just on input tokens for one session — assuming no prompt caching wins, which degrade as history grows.

**Fix:** Track cumulative input+output tokens in `SessionContext`, abort after a configurable cap (`--max-dollars` or `--max-tokens`). The spec's open-question list includes cost-optimisation as v2, but a hard cap should be v1 — a runaway agent on a nightly cron is the textbook ops incident.

Add to `SessionContext`:
```
cumulative_input_tokens: int = 0
cumulative_output_tokens: int = 0
max_input_tokens: int = 2_000_000   # default; overridable
max_output_tokens: int = 200_000
```

After each `resp` return in the loop:
```
ctx.cumulative_input_tokens += resp.usage.input_tokens
ctx.cumulative_output_tokens += resp.usage.output_tokens
if ctx.cumulative_input_tokens > ctx.max_input_tokens:
    ctx.transcript.log({"event": "token_cap_hit", ...})
    break
```

This adds ~4 lines of code and caps the worst-case cost deterministically.

**Severity:** High. First time a prompt regression makes the agent loop on `describe_wizard_state` for 200 turns, we pay for it.

---

### 2.2 HIGH — Prompt-cached system + tools will silently miss on every turn after ~5 min

**Location:** Spec §Architecture (prompt caching), `agent_loop.py`.

**Problem:** The Anthropic `cache_control: {"type": "ephemeral"}` cache has a 5-minute TTL (confirmed by Anthropic docs + general claude-api skill guidance). On a 15-minute session, the cache will expire mid-session. The loop never refreshes the cache marker; every subsequent turn after the cache expires pays full input cost again. This doesn't break anything but erases the cost savings the spec claims.

**Fix:** Either (a) accept the cost (spec gets revised to ~\$3-7/run), or (b) refresh the cache by re-sending the same system+tools text every ~4 minutes in a "keepalive" no-op turn. (a) is simpler; (b) complicates the loop.

Recommend (a) + spec revision. Note in the plan that cache hit rate is only good for the first few turns, and the real cost per run is closer to \$5 at 15 min than \$2.

**Severity:** High as a cost-model error; Medium for user impact (off by 2x on predicted cost).

---

### 2.3 MEDIUM — `page_body_text` truncation at 16 KB could hide the traceback it's meant to find

**Location:** `tools/browser.py::page_body_text`, `_BODY_TEXT_MAX = 16_384`.

**Problem:** The agent uses `page_body_text` to scan for `Traceback (most recent call last):`. If the wizard has a verbose log viewer (setup.js does — `#log-output` accumulates pipeline stderr), the total `document.body.innerText` could easily exceed 16 KB, and the traceback could be BELOW the truncation point. Agent reads, finds nothing, reports no finding. False negative.

**Fix:** Either (a) keep the 16 KB cap but document that the agent should prefer `page_inner_text` on specific selectors (more targeted), or (b) when truncating, search the full text for the Traceback marker and return a window around it if found. (b) is safer for the specific class we care about:

```python
async def page_body_text(self) -> dict:
    text = await self.page.inner_text("body")
    # Prefer: if a traceback marker is present, return a 4KB window around it.
    marker = "Traceback (most recent call last):"
    idx = text.find(marker)
    if idx >= 0:
        start = max(0, idx - 256)
        end = min(len(text), idx + 4_096)
        return {"text": text[start:end], "truncated": len(text) > end - start,
                 "marker": "traceback_window"}
    return {"text": text[:_BODY_TEXT_MAX], "truncated": len(text) > _BODY_TEXT_MAX}
```

Add this to Task 2 Step 4. Also update the unit test `test_page_body_text_is_truncated_at_16kb` to handle both cases.

**Severity:** Medium. Only fires for long log-viewer content, but that's exactly the pipeline-start failure class the agent is meant to catch.

---

### 2.4 MEDIUM — No replay / debuggability for failed tool calls

**Location:** `agent_loop.py` exception handler.

**Problem:** When a tool handler raises, the loop catches `Exception` and reports `{"error": "Foo: bar"}` to the agent. The exception stack trace is lost. Debugging a tool regression means staring at a transcript JSONL with `{"event": "tool_result", "id": "...", "result": {"error": "..."}}` and guessing what happened.

**Fix:** Log the traceback to the transcript even though it's not sent to the model:

```python
except Exception as e:
    import traceback
    tb = traceback.format_exc()
    result = {"error": f"{type(e).__name__}: {e}"}
    ctx.transcript.log({
        "event": "tool_error",
        "tool_name": block.name,
        "traceback": tb,
    })
```

Single line of code; huge debuggability win.

**Severity:** Medium. Will bite the first time a tool regresses in production.

---

## Round 3 — Security

**Persona:** A security-minded reviewer who read the OWASP LLM top 10 last week.

### 3.1 HIGH — `container_run_command` is unrestricted — spec handwaves the security model

**Location:** Spec §Tool surface invariants #4 and `tools/container.py`.

**Problem:** The spec says "container_run_command is unrestricted — the LXD container is ephemeral and deleted at run end; destructive ops are expected." That's true for the container. It's NOT true for the host:

- The command runs via `lxc exec $CONTAINER -- bash -c "$command"` on the host. The host process `lxc exec` runs as the host user (the CI runner or the developer's user).
- If the container's filesystem includes a mount back to the host (LXD `disk` device), `cat /host/...` leaks host data into `stdout` which the agent then reads.
- The CI runner IS the production Pi. If the agent's `container_run_command` somehow escapes (unlikely, but LXD escape CVEs exist — CVE-2021-36155, CVE-2022-0185), it runs as the runner's user. On Geographica's Pi, that user is `administrator`.
- Prompt injection: if the wizard ever renders any user-controllable content that the agent reads back via `page_body_text`, a malicious payload could redirect the agent to issue `container_run_command` with hostile payloads.

**Fix:**
- State the threat model explicitly in the spec: assumes (a) no mount from host into container, (b) the LXD container is a trust boundary strong enough to contain the agent.
- The `wizard-ci.sh` flow satisfies (a) today (pushes a tar, nothing mounted). Add a test that verifies `lxc config show $CONTAINER | grep -v 'type: disk'` for disk devices OTHER than the root. Actually that's too strict — the root is type `disk`. The check should verify no `source:` pointing at a host path outside the container.
- For (b), document the CVE awareness and state that nightly exploratory runs are fine but exploratory mode should NEVER be invoked on a CI runner that carries production secrets. The self-hosted Pi IS our production box, so consider moving nightly runs to a dedicated runner or a disposable Pi 5 in v2.

**Severity:** High — as a threat-model gap. Low — as a practical exploit, given no known agent-driven LXD escape. Still, the spec should name the assumption.

---

### 3.2 MEDIUM — `container_fs_write` allows `/run` — could clobber CSRF token

**Location:** `tools/container.py::_ALLOWED_WRITE_ROOTS = ("/srv/", "/tmp/", "/run/")`.

**Problem:** `/run/geographica-setup/csrf-token` is exactly the file the wizard persists the CSRF token to. An agent that writes a garbage token to that file during a session can confuse subsequent `container_restart_wizard` behaviour and produce false-positive CSRF findings. Also, the agent can trivially test the "what if the CSRF file is corrupt" scenario — which IS a valid test — but the resulting finding would be "I broke it myself, now it's broken," not a real bug.

**Fix:** Either (a) keep `/run` writable but add a note in the system prompt that `container_fs_write` to `/run/geographica-setup/csrf-token` is a deliberate disruption tool, not a bug-finder, or (b) block that specific path. Recommend (a) — the disruption is useful. But require that every finding whose reproduction includes `container_fs_write` to a critical-path file also state "this is post-disruption behaviour" so human reviewers can weight it accordingly.

Add this to `bug_classes.md` under a new §Self-disruption caveat.

**Severity:** Medium. Will inflate the false-positive rate on first real runs.

---

### 3.3 LOW — `ANTHROPIC_API_KEY` usage is documented but key-rotation story isn't

**Location:** Spec §Integration with existing harness, Plan Task 8.

**Problem:** The plan says "requires ANTHROPIC_API_KEY secret on the self-hosted Pi runner." No mention of:
- Who provisions the key.
- What happens on rotation.
- What scope the key should have (restricted to specific models? spending cap?).
- Whether the key is logged anywhere (it shouldn't be; verify the transcript doesn't accidentally include it).

**Fix:** Add a § to the spec titled "Secret management":
- Key is provisioned as a GitHub Actions organization secret named `ANTHROPIC_API_KEY`.
- Key SHOULD have a monthly spending cap configured on the Anthropic console (recommend \$100 to start; well above the expected ~\$30/mo for nightly runs).
- Transcript writer MUST filter request/response bodies for `Authorization:` and `x-api-key:` headers before logging. Add a unit test.

**Severity:** Low per-incident; High cumulatively if a leaked key runs up a bill.

---

## Round 4 — Evaluation quality

**Persona:** A skeptical QA engineer who's seen one too many "AI testing" products overpromise.

### 4.1 HIGH — Spec has no explicit signal-to-noise target

**Location:** Spec §Acceptance criteria.

**Problem:** Acceptance criterion #4 says "≥0 findings" on current main — literally "any number works." That's not an acceptance criterion, it's a shrug. Without a target signal-to-noise ratio, the harness can stay useless indefinitely while passing all acceptance tests. For example: an agent that reports every input as suspicious passes #4 with 50 findings, 0 of which are real.

**Fix:** Replace #4 with a concrete target. Propose:

> On the current `main`, after three consecutive nightly runs, at least 40% of findings must be confirmed real bugs (tracked in `dev/harness/findings/reviewed.md` with disposition: real / dismissed). Below 40% triggers a prompt-engineering revision.

Also: on a run against a rollback fixture, at least ONE finding must match the target bug class within the first 10 minutes of agent runtime. (Acceptance criterion #3 already implies this, but doesn't time-bound it.)

**Severity:** High. Without this, there's no definition of success.

---

### 4.2 HIGH — Findings aren't de-duplicated

**Location:** `ReportingTools.report_finding_sync` and the spec §Reporting rules.

**Problem:** The system prompt tells the agent "maintain an internal list; do not duplicate." But in a 200-turn session the agent's own context will drop earlier tool calls out of working memory. It WILL re-report the same bug under slightly different framings. Humans then have to de-duplicate by hand during review. That's expensive and error-prone.

**Fix:** Hash-dedupe at `report_finding_sync` time. Compute a coarse hash of `(classification, title-normalized, sorted(input-keys))` and, if it collides with an existing finding's hash, return the existing ID instead of creating a new one:

```python
def _hash(self, classification, title, input):
    import hashlib
    norm_title = re.sub(r"\W+", " ", title.lower()).strip()
    key = f"{classification}|{norm_title}|{sorted(input.keys())}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]

def report_finding_sync(self, *, classification, title, input, **kw):
    h = self._hash(classification, title, input)
    if h in self._hashes:
        return {"id": self._hashes[h], "deduped": True}
    fid = f"F-{len(self.findings) + 1:03d}"
    self._hashes[h] = fid
    # ...
```

Add to Task 5 with a corresponding unit test (`test_report_finding_dedups_on_identical_title_and_input`).

**Severity:** High. Without dedup, findings files will be 80%+ duplicates and human review becomes unusable.

---

### 4.3 MEDIUM — No comparison to baseline / known-good run

**Location:** Spec §Out-of-scope ("statistical analysis of findings over time").

**Problem:** When the agent produces 12 findings today and 18 tomorrow, which is the new bug? Without a baseline "on current main, this is the stable set of findings," every nightly run is reviewed from scratch. Reviewer fatigue kills the workflow within a month.

**Fix:** v1 is fine, but add one concrete mitigation: the findings file should include a `findings_hash` header (hash of the set of `_hash`es from Issue 4.2). Reviewer can run a quick `diff <(grep -E "^## Finding" findings/yesterday.md) <(grep -E "^## Finding" findings/today.md)` to see only the new ones. The `checkpoint` file `findings/reviewed.md` from 4.1 also helps here — "everything hashed from reviewed.md is known."

Add this to Task 5 findings_writer: include a `findings_hashes:` block in the YAML frontmatter. Add to Task 10 README a paragraph on the "diff against yesterday" review workflow.

**Severity:** Medium. Mitigates reviewer fatigue.

---

### 4.4 MEDIUM — Nothing prevents the agent from discovering the same known bug every run

**Location:** `bug_classes.md` "Already-known bug classes" section.

**Problem:** The seed file lists the 5 April bugs with "don't re-discover these" instructions. But the agent is stateless across runs. Every nightly run starts with the full seed list. If, five months from now, the seed has 40 "don't re-discover" items, the prompt alone is 10 KB of exclusions. Prompt-cache hits help but don't prevent the agent from considering each one and deciding "oh this is known, skip."

**Fix:** In the longer term (v2), trim the seed list when a bug is marked resolved AND confirmed regression-tested in drive-wizard.mjs. The deterministic harness then enforces the fix; the seed list shouldn't also. In v1, accept the prompt growth and plan a v2 cleanup pass.

**Severity:** Medium. Not a v1 blocker, but note it explicitly so the plan author doesn't forget.

---

## Summary

**Must fix before implementation:** 1.1 (asyncio API), 1.2 (schema validation), 1.3 (describe_wizard_state stub), 2.1 (token cap), 4.2 (dedup).

**Should fix before first real run:** 1.5 (unit-name coupling), 2.3 (traceback window in body_text), 2.4 (traceback logging), 3.1 (document threat model), 3.3 (secret handling), 4.1 (signal-to-noise target).

**Can defer to v2:** 3.2 (self-disruption caveat — just add prompt note), 4.3 (findings diff), 4.4 (seed-list growth).

All of these are actionable inline edits to the plan — none require re-scoping the feature.
