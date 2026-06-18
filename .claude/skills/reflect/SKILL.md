---
name: reflect
description: Distill episodic memory into reusable rules and prune low-signal episodes. Run periodically (every 5-10 episodes, or after a major project milestone) to convert raw experience into durable system knowledge. The system gets better over time through this mechanism.
argument-hint: "[optional: focus area or specific episode to reflect on]"
---

# Reflect — Episodic Memory Distillation

Convert accumulated experience into reusable system knowledge.
Focus: **$ARGUMENTS**

Current episodes:

!`ls -la .claude/memory/episodes/ 2>/dev/null | grep -v gitkeep || echo "No episodes yet"`

---

## Phase 1 — Survey Episodes

Read all episode files in `.claude/memory/episodes/`. For each, extract:
- The RULE extracted
- The signal strength (HIGH / MEDIUM / LOW)
- Whether it duplicates or contradicts an existing rule in `.claude/rules/`

Organize by theme (e.g., "delegation patterns", "security oversights", "context scoping").

---

## Phase 2 — Distill HIGH-signal Rules

For each HIGH-signal rule that is not already captured in `.claude/rules/`:

1. **Validate it generalizes.** Is this a one-off fluke or a pattern that will recur?
   A rule from a single episode needs corroboration. A rule from multiple episodes is
   strong.

2. **Write a rule file** in `.claude/rules/` with:
   - A descriptive name
   - A `paths:` scope if it only applies to certain file types
   - The rule, stated as a positive directive ("When X, do Y because Z")
   - The source episodes that back it

3. **Or update an existing rule** if the episode refines or strengthens an existing one.

For MEDIUM-signal rules: keep the episode for now. If a second episode corroborates, the
pattern is confirmed — distill it then.

---

## Phase 3 — Prune Low-Value Episodes

Episodes are NOT meant to accumulate forever. Memory bloat degrades retrieval quality
(EvolveMem research: utility-based deletion outperforms keep-everything by ~10%).

Delete an episode when:
- Its rule has been distilled into `.claude/rules/` (the knowledge is preserved; the
  raw evidence is no longer needed)
- It is LOW-signal AND older than 10 episodes without corroboration
- It duplicates another episode's lesson without adding new information

Do NOT delete an episode when:
- It is the only evidence for an undistilled HIGH-signal rule
- It records a failure whose root cause is not yet fully understood
- It contradicts an existing rule (contradictions are valuable — they may signal the
  rule needs refinement)

---

## Phase 4 — Audit the Rule Base

Review `.claude/rules/` for:
- **Contradictory rules** — two rules that give opposite advice. Resolve based on the
  evidence. If the evidence is ambiguous, note the condition that determines which applies.
- **Stale rules** — rules that reference patterns or files that no longer exist.
- **Over-broad rules** — rules stated too generally that may cause false positives.
  Narrow the scope (add `paths:`, add conditions).

---

## Phase 5 — Report

```
## Reflection Summary

### Rules Distilled
- [rule name] — from episodes [list] — added to .claude/rules/[file]

### Episodes Pruned
- [episode] — reason: [already distilled / low signal / duplicate]

### Episodes Retained
- [episode] — reason: [unresolved / awaiting corroboration / valuable contradiction]

### Rule Base Health
- Total rules: N
- Contradictions found: N
- Stale rules removed: N

### System Learning
[One paragraph: what is the system getting better at? What patterns are emerging?
What gaps remain?]
```
