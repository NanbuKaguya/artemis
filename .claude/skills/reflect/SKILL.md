---
name: reflect
description: Distill episodic memory into reusable rules. Run every 5-10 episodes or after a major milestone. Enforces a token budget on learned rules to prevent bloat — quality over quantity. The system gets better through this loop, not through accumulation.
---

# Reflect

## Step 0 — Token Budget Check

Count the tokens in `.claude/rules/learned.md` (create it if it doesn't exist).
If it exceeds 800 tokens: you must prune before adding anything new. This is a hard constraint.

## Step 1 — Survey Episodes

Read every file in `.claude/memory/episodes/`. For each episode, ask:
- **What specific decision would have been different with this knowledge?**
- **Is there a pattern across 2+ episodes?**

Episodes that can't answer the first question are LOW signal. Note them for pruning.

## Step 2 — Distill Rules

A rule earns a place in `learned.md` only if:
1. It appears in **2+ independent episodes** (single episode = not yet verified)
2. It answers a **specific decision question** (not "be more careful" or "think harder")
3. It's short enough to be processed: **two sentences maximum**

Write HIGH-signal rules to `.claude/rules/learned.md`:
```markdown
## [Rule Title]
[Sentence 1: the situation this applies to.]
[Sentence 2: what to do differently.]
Source: episodes/[slugs]
```

## Step 3 — Prune

From `learned.md`, remove rules that are:
- Superseded by a better, more specific rule
- Too vague to change a decision ("verify everything" is not a rule)
- Contradicted by newer evidence

From `.claude/memory/episodes/`, remove episodes that:
- Have been successfully distilled into a rule (archive or delete)
- Are LOW signal and have no pattern match after review

## Step 4 — Report

State: rules added (with the decision they address), rules pruned (with reason), episodes pruned, current token count in `learned.md`.

The measure of a good reflect session is not how many rules you added. It's the signal density of what remains.
