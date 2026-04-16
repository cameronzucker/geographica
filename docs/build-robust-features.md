Invoke the superpowers brainstom skill for the requested features, fixes, or other specified project to-dos.

Once brainstorm is complete, run a 5 round adversarial agent review (ensure Codex is used at least once). When complete, run /write-plan skill to create the action plan, considering the following:

Invoke `/writing-plans` to create an implementation plan. The plan file MUST be saved to `docs/plans/<date>-<slug>-plan.md` (e.g., `docs/plans/2026-03-18-phase11-mfa-bug-hunt-remediation-plan.md`).

When `/writing-plans` presents execution options, **include a recommendation** for which approach would be most effective. The three options are: (1) subagent-driven in this session, (2) parallel session with `/executing-plans` in a worktree, or (3) Agent Teams for multi-agent parallel execution. Base the recommendation on: how much context this session has consumed, whether the plan is self-contained enough for a fresh session, how many tasks are parallelizable vs sequential, and whether any tasks are risky enough to warrant focused attention rather than parallel dispatch. Explain the reasoning concisely.

### Critical requirements for the plan

The plan will be executed via `/subagent-driven-development` or `/executing-plans`. Subagents are powerful but fail in predictable ways. The plan MUST be written to prevent these failures:

1. **Eliminate ambiguity.** For each task, specify:
   - The exact files to modify
   - The exact behavior change (current behavior → desired behavior)
   - The exact test to write (input, expected output, edge cases)
   - Whether the fix requires coordination with other tasks (ordering dependencies)

2. **Prevent context gaps.** Subagents start fresh with no conversation history. Each task description must be self-contained:
   - Include the bug evidence (file:line, what's wrong)
   - Include the fix approach (don't just say "fix the bug")
   - Include relevant architectural context from PLAN.md if the fix depends on understanding a design choice
   - If the fix touches shared code, explicitly list other callers that must still work

3. **Prevent interpretation drift.** Where there's only one correct fix, state it explicitly. Don't leave room for a subagent to "improve" or "enhance" the fix beyond what's needed. Where there are multiple valid approaches, pick one and specify it — don't let the subagent choose.

4. **Mandate TDD and testing discipline.** Every task MUST include this preamble:
   ```
   BEFORE starting work:
   1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
   2. Read dev/testing-pitfalls.md
   Follow TDD: write failing test → implement fix → verify green.
   ```
   Every task MUST include this completion check:
   ```
   BEFORE marking this task complete:
   1. Review your tests against dev/testing-pitfalls.md
   2. Verify test coverage of the fix (are error paths tested? edge cases?)
   3. Run tests (or relevant subset) and confirm green
   ```
   Every logical group of tasks MUST include this review loop:
   ```
   After every logical group of tasks:
   You MUST carefully review the batch of work from multiple perspectives
   and revise/refine as appropriate. Repeat this review loop (you must do
   a minimum of three review rounds; if you still find substantive issues
   in the third review, keep going with additional rounds until there are
   no findings) until you're confident there aren't any more issues. Then
   update your private journal and continue onto the next tasks.
   ```

5. **Review against `docs/pitfalls/testing-pitfalls.md`.** Read it yourself and check whether any of the planned work could fall into documented testing pitfalls. If so, add explicit warnings to the relevant task descriptions.

6. **Review against `docs/pitfalls/implementation-pitfalls.md`.** Read it yourself and check whether any of the planned work could fall into documented testing pitfalls. If so, add explicit warnings to the relevant task descriptions.

7. **Group tasks to minimize cross-task conflicts.** If two tasks touch the same file, they should be in the same task or explicitly sequenced. Parallel subagents editing the same file will create merge conflicts.

--------

Plan Review Cycle

Before committing, rigorously review the  plan for subagent-readiness.

Carefully review the plan from multiple perspectives and revise/refine as appropriate. Repeat this review loop (you must do a minimum of three review rounds; if you still find substantive issues in the third review, keep going with additional rounds until there are no findings) until you're confident there aren't any more issues. Specifically consider:

- **Ambiguity:** Are there task descriptions where a subagent could reasonably interpret the instructions two different ways? Eliminate every instance.
- **Context gaps:** Would a subagent starting fresh (no conversation history) have everything it needs to complete each task correctly? Check for implicit assumptions.
- **Unclear instructions:** Are there vague directives like "fix the issue" or "handle this correctly" instead of specific behavioral descriptions?
- **Undesirable interpretation latitude:** Are there areas where a subagent might "improve" or "enhance" beyond scope? Add explicit "do NOT" boundaries where needed.
- **Cross-task dependencies:** Are ordering constraints clearly stated? Would a subagent working on Task 3 know it depends on Task 1 completing first?
- **Testing pitfalls:** Review the plan against `docs/pitfalls/testing-pitfalls.md` — could any planned test additions fall into documented pitfalls? Add warnings to relevant tasks.
- **Implementation pitfalls:** Review the plan against `docs/pitfalls/implementation-pitfalls.md` Could any planned tasks fall into documented pitfalls?

After completing the review cycle, update your private journal with observations about the plan quality and any patterns in the issues you found.