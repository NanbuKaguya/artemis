---
name: critical-decision
description: Structured adversarial debate for high-stakes decisions. Dispatches proponent and skeptic agents in parallel with strict context isolation, then a consensus-judge adjudicates. Use for security-critical code, architecture decisions, irreversible operations, or any decision where the cost of error is high.
argument-hint: "[decision or artifact to evaluate]"
---

# Critical Decision — Structured Adversarial Debate

Evaluate a high-stakes decision via structured debate: **$ARGUMENTS**

This skill exists because single-reviewer verification has a ceiling. For decisions where
the cost of error is high, structurally opposed advocates produce better outcomes than
any single reviewer — IF they are properly isolated.

---

## Pre-check

Is this actually high-stakes? This skill adds significant token cost (~3x a single
review). Use it when:
- Security-critical code or configuration
- Architecture decisions that are hard to reverse
- Irreversible operations (data migration, deletion, breaking changes)
- Decisions where two reasonable people could disagree

If the change is routine, use `/quality-gate` instead.

---

## Phase 1 — Dispatch Advocates (PARALLEL, ISOLATED)

Invoke the `proponent` and `skeptic` agents **in parallel** (two `Agent` calls in one
message) with **strict context isolation**:

### Proponent receives:
```
## Artifact
[The artifact or decision to evaluate — code, design, plan]

## Context
[What this is meant to accomplish and the constraints it operates under]

## Your Role
Argue that this solution is correct, complete, and fit for purpose.
Present the strongest honest case FOR acceptance.

## Output Contract
{ position, arguments: [{claim, evidence, strength}],
  acknowledged_weaknesses: [string], bottom_line }
```

### Skeptic receives:
```
## Artifact
[SAME artifact — identical to what the proponent received]

## Context
[SAME context — identical]

## Your Role
Argue that this solution is flawed, incomplete, or unfit for purpose.
Present the strongest honest case AGAINST acceptance.

## Output Contract
{ position, arguments: [{claim, evidence, severity}],
  acknowledged_strengths: [string], bottom_line }
```

### CRITICAL ISOLATION RULES:
- Proponent and skeptic NEVER see each other's arguments during analysis.
- Neither receives the orchestrator's opinion or preference.
- Both receive IDENTICAL artifacts and context — no information asymmetry.
- Both are invoked in PARALLEL to prevent sequential contamination.

Violating isolation produces sycophancy collapse: agents converge to agreement regardless
of the artifact's quality, defeating the purpose of debate.

---

## Phase 2 — Adjudicate

Invoke the `consensus-judge` agent with BOTH arguments + the original artifact:

```
## Artifact
[The original artifact — same as advocates received]

## Proponent's Case
[Full proponent output]

## Skeptic's Case
[Full skeptic output]

## Decision Criteria
[What "correct" means for this specific decision — from the original acceptance criteria]

## Your Role
Evaluate both arguments on evidence and reasoning. Deliver a verdict.

## Output Contract
{ verdict: ACCEPT|REJECT|MODIFY, reasoning, conditions: [string]|null,
  dissent_acknowledged }
```

---

## Phase 3 — Report

Present the verdict to the user:

```
## Critical Decision: [subject]

**Verdict: [ACCEPT / REJECT / MODIFY]**

### Proponent's strongest argument:
[1-2 lines]

### Skeptic's strongest argument:
[1-2 lines]

### Judge's reasoning:
[Key points from adjudication]

### Conditions (if MODIFY):
[What must change]

### Dissent acknowledged:
[What the losing side got right]
```

If the verdict is REJECT or MODIFY, the work is not ready. The findings feed back into
the implementation cycle. If ACCEPT, the work can proceed to `/ship`.

---

## Failure Mode Awareness

This debate process can fail in specific ways. Watch for:

1. **Sycophancy collapse** — both advocates agree despite obvious issues. Symptom:
   skeptic's "acknowledged strengths" section is longer than its arguments. If this
   happens, the isolation was likely violated or the artifact has no real issues.

2. **Manufactured dissent** — skeptic invents issues to fill its role. Symptom: findings
   are vague ("might have issues") rather than concrete ("line 42 throws null when...").
   The judge should filter these.

3. **Judge deference** — judge picks the more eloquent argument instead of the more
   evidenced one. Symptom: verdict reasoning cites persuasiveness rather than evidence.
   Re-run with an explicit reminder to evaluate evidence, not rhetoric.
