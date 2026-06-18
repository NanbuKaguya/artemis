---
paths:
  - ".claude/agents/**"
  - ".claude/skills/**"
---

# Handoff Contract Standard

Every agent-to-agent handoff uses a structured format. Free-form handoffs are the #1
source of multi-agent failure (41.8% of failures in the MAST taxonomy are
specification/coordination problems).

## Delegation Prompt Format (Orchestrator → Specialist)

When the Orchestrator dispatches a task via the `Agent` tool, the prompt MUST contain
these sections in order:

```
## Task
[One-line description of what to accomplish]

## Context
[Scoped: only the files, outputs, or facts this task needs — never "read everything"]

## Input
[The specific artifact(s) being handed to this agent — diff, file list, prior output]

## Output Contract
[Exact format the agent must return — e.g., "a list of findings as {severity, file,
line, issue, fix}" or "updated file at path X"]

## Acceptance Criteria
[How the Orchestrator will judge success — measurable, not vague]
```

## Agent Response Format (Specialist → Orchestrator)

Agents return structured output matching their declared output contract:

```
## Result
[The deliverable in the contracted format]

## Confidence
[HIGH / MEDIUM / LOW — with one-line justification]

## Flags
[Anything the Orchestrator should know: risks found, scope exceeded, assumptions made]
```

## Inspector Handoff (Orchestrator → Inspector)

The Inspector receives ONLY:

```
## Artifact
[The output to inspect — code diff, plan, document — with NO generator context]

## Inspection Mandate
[What to look for: correctness bugs, security issues, specification violations, etc.]

## Output Contract
{ findings: [{severity: Critical|High|Medium|Low, location: string, issue: string,
  fix: string}], verdict: PASS | FAIL | CONDITIONAL, summary: string }
```

The Inspector NEVER receives: the generator's reasoning, the orchestrator's planning
context, or why the artifact was produced the way it was.
