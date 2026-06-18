---
name: quality-gate
description: Run the verification battery before declaring work done. Use after implementing a change and before reporting success or shipping.
argument-hint: "[optional: area or scope to focus on]"
---

# Quality Gate

Verify the work is actually done — by evidence, not assertion. Scope: **$ARGUMENTS**

Current changes under review:

!`git status --short`

Run the checks that apply to this change. Do not claim a check passed without running it;
if a step is skipped or N/A, say so explicitly.

1. **Builds / compiles** — Run the project's build. Zero errors.

2. **Tests pass** — Run the relevant test suite (and the full suite before delivery). Show
   the actual result. New behavior must have new tests.

3. **Lint / format / types** — Run the project's linter, formatter, and type checker.

4. **Review the diff** — Read `git diff` end to end. For any non-trivial change, delegate
   to the `code-reviewer` agent and resolve must-fix findings.

5. **Security spot-check** — No secrets added, inputs validated, no obviously unsafe
   patterns. For security-sensitive changes, delegate to `security-auditor`.

6. **Behavioral check** — Where feasible, observe the change actually working (run it /
   exercise the path), not just that it compiles.

7. **Scope & hygiene** — Diff is minimal and on-topic; no stray debug code, no unrelated
   churn; matches the surrounding code's style.

**Report** a short pass/fail checklist with evidence. State plainly whether the work is
ready. If anything failed, show the output and stop — do not declare success.
