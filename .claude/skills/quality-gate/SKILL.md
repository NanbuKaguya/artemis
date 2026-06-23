---
name: quality-gate
description: Verification pipeline before declaring work done. Deterministic checks first (tests, lint, type, secrets), then adversarial model review. Use after implementing any non-trivial change and before reporting success.
---

# Quality Gate

Run this before declaring any non-trivial work complete.

## Phase 1 — Deterministic Checks

Run whatever applies to the changed code. Paste the real output.

```bash
# Tests (use the project's actual command)
npm test / pytest / go test ./... / cargo test

# Lint
eslint . / flake8 / golangci-lint run / clippy

# Type checks
tsc --noEmit / mypy . / pyright

# Secret scan on staged changes
git diff HEAD | grep -iE "(password|secret|token|api_key)\s*=\s*['\"][^'\"]{4,}" | grep -v "test\|example\|placeholder"

# What actually changed
git diff --stat HEAD
```

**If Phase 1 fails:** stop. Report the failure with full output. Fix it. Do not proceed to Phase 2 until Phase 1 is green.

## Phase 2 — Adversarial Review

Invoke `inspector` with:

```
## Artifact
[git diff HEAD — the actual diff output]

## Inspection Mandate
Find: correctness bugs, security vulnerabilities, contract violations, and logic errors.
Assume errors were made. This is the artifact only — no context about how it was built.
```

The inspector gets the artifact cold. No context. No explanation. That is the mechanism.

## Verdict

| Result | Action |
|---|---|
| Phase 1 fails | Fix before anything else. Full output in report. |
| Inspector: FAIL | Address all Critical and High before shipping. |
| Inspector: CONDITIONAL | Address stated conditions. Document any Medium/Low deferral and why. |
| Inspector: PASS | Ship. |

Done = Phase 1 green + Inspector PASS or CONDITIONAL with conditions addressed.
