---
name: quality-gate
description: Adversarial verification pipeline. Runs structurally separated inspection on the current work before declaring it done. The Inspector receives only the artifact, never the generator's context. Use after implementing a change and before reporting success or shipping.
argument-hint: "[optional: area or scope to focus on]"
---

# Quality Gate — Adversarial Verification Pipeline

Verify the current work by evidence and structural inspection — not self-review.
Scope: **$ARGUMENTS**

Current state:

!`git diff --stat HEAD`

---

## Phase 1 — Mechanical Checks (run directly, no delegation needed)

Run every applicable check. Report real output. Skip = state why.

1. **Build** — Run the project's build command. Zero errors.
2. **Tests** — Run the relevant test suite (full suite before delivery). Show output.
3. **Lint / format / types** — Run the project's linter, formatter, type checker. Show output.
4. **No secrets** — Grep the diff for patterns: API keys, tokens, passwords, private keys.

```
!`git diff HEAD -- . ':!*.md' | grep -iE '(api.?key|secret|token|password|private.?key|BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE)' || echo "No secret patterns found"`
```

If any mechanical check fails, stop here. Do not proceed to inspection with known
failures — fix first, then re-run the gate.

---

## Phase 2 — Structural Inspection (MANDATORY for non-trivial changes)

**This is the core of the quality gate.** Invoke the `inspector` agent (or
`code-reviewer` for code changes) as a SEPARATE agent with an ADVERSARIAL mandate.

### What the Inspector receives:

```
## Artifact
[The git diff or the relevant output — ONLY the artifact]

## Inspection Mandate
Review for: correctness bugs (logic errors, edge cases, error handling),
security issues (injection, authz, data exposure), and specification
compliance (does it meet the stated acceptance criteria).

## Output Contract
{ findings: [{severity: Critical|High|Medium|Low, location, issue, fix}],
  verdict: PASS|FAIL|CONDITIONAL, summary }
```

### What the Inspector does NOT receive:
- The generator's reasoning or thought process
- The orchestrator's planning context
- Why the code was written this way
- Any "heads up" about known issues

The Inspector reads the artifact cold and judges it on its merits.

### Interpreting the verdict:

- **PASS** — no Critical or High findings. Proceed to Phase 3.
- **CONDITIONAL** — no Critical, but High findings that may be acceptable. Review the
  conditions. If acceptable, document why and proceed. If not, fix and re-inspect.
- **FAIL** — Critical or High findings exist. Fix them. Re-run the gate from Phase 1.
  Do NOT skip re-inspection after fixing — the fix itself could introduce new issues.

---

## Phase 3 — Scope & Hygiene (quick, direct)

1. **Diff is minimal and on-topic** — no stray debug code, no unrelated churn.
2. **Matches surrounding code style** — naming, idiom, structure consistent.
3. **New behavior has new tests** — if the change adds functionality, tests exist for it.

---

## Phase 4 — Verdict

Produce a pass/fail checklist with evidence:

```
## Quality Gate Results

Mechanical:
- [ ] Build:    [PASS/FAIL] — [output summary]
- [ ] Tests:    [PASS/FAIL] — [X passed, Y failed]
- [ ] Lint:     [PASS/FAIL] — [output summary]
- [ ] Secrets:  [PASS/FAIL] — [none found / FOUND: ...]

Inspection:
- [ ] Inspector verdict: [PASS/FAIL/CONDITIONAL]
- [ ] Findings: [count by severity, or "none"]
- [ ] Must-fix: [list, or "none"]

Hygiene:
- [ ] Minimal diff: [yes/no]
- [ ] Style match: [yes/no]
- [ ] Tests for new behavior: [yes/no/N/A]

## Overall: [PASS / FAIL — reason]
```

**State plainly whether the work is ready.** If anything failed, show the output and
stop. Do not declare success with unresolved findings.

---

## Escalation to /critical-decision

If the work involves security-critical code, irreversible operations, or architectural
decisions, escalate to `/critical-decision` which runs the full proponent → skeptic →
judge debate. The quality gate alone is not sufficient for high-stakes changes.
