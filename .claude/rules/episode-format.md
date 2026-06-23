---
description: Format for writing episodic memory entries
globs: [".claude/memory/episodes/**"]
---

# Episode Format

Write an episode after: a task failure, an unexpected outcome, a hard-won insight, or anytime you think "I wish I'd known this earlier."

**File:** `.claude/memory/episodes/YYYY-MM-DD-<slug>.md`

**Content — write exactly these four sections:**

```markdown
## What happened
[One paragraph: the task, what went wrong or was surprising, the outcome]

## Root cause
[One sentence: the underlying reason — not the symptom]

## What changes next time
[One or two sentences: the specific decision or action that should be different]

## Signal
HIGH | MEDIUM | LOW — will this change a future decision?
```

**The test for whether to write an episode:** Would this have changed your approach if you'd known it at the start? If yes, write it. If it's just "things went fine," don't write it — you're accumulating noise.

**The test for a good episode:** Can `/reflect` distill it into a specific, actionable rule? If the "what changes next time" is vague, rewrite it until it's concrete.
