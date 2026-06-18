---
paths:
  - ".claude/memory/episodes/**"
---

# Episode Record Format

Episodes are the system's experience memory. Each records what happened, why, and what
was learned — especially from failures, surprises, or hard-won insights.

## Template

Every episode file follows this structure. File name: `YYYY-MM-DD-<slug>.md`

```markdown
# Episode: <date> — <short description>

## Task
What was attempted and what the success criteria were.

## Topology
Which coordination topology was used (SOLO/SEQUENTIAL/PARALLEL-FANOUT/HIERARCHICAL).

## Outcome
What actually happened — success, partial, or failure. Include real output/evidence.

## Process
Which agents were involved, what each did, where handoffs succeeded or failed.

## Root Cause (for failures/surprises)
Why the unexpected thing happened. Not a guess — trace it to a specific cause.

## Rule Extracted
RULE: When [specific condition], [specific action] instead of [default behavior].
Because: [evidence from this episode].

## Signal Strength
HIGH — This was a clear, repeatable lesson.
MEDIUM — This was informative but may be context-specific.
LOW — Minor observation, may not generalize.
```

## Guidelines

- Write episodes **promptly** after the task, while evidence is fresh.
- Be concrete: "the security-auditor missed the SQL injection on line 42 because the
  context brief didn't include the database schema" — not "the review could have been
  better."
- One episode per significant task or incident. Don't over-record routine work.
- The RULE field is the most important part — it's what `/reflect` distills into
  `.claude/rules/` entries. Make it specific and actionable.
- Mark signal strength honestly. Not every episode is a HIGH lesson.
