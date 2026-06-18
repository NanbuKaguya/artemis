---
name: plan-work
description: Turn a goal into a framed, owner-assigned task plan before any implementation. Use at the start of any non-trivial or multi-domain piece of work.
argument-hint: "[goal or task description]"
---

# Plan Work

Produce an execution plan for: **$ARGUMENTS**

Follow the Artemis planning loop. Keep it tight — this is a plan, not implementation.

1. **Frame** — Restate the goal, the success criteria, and the hard constraints in 2–4
   lines. List any assumptions you are making to resolve ambiguity.

2. **Survey** — Read only what you need to plan accurately (`CLAUDE.md`, `README`, the
   directories the work touches). Note existing patterns to reuse.

3. **Decompose** — Produce an ordered task table:

   | # | Task | Owner (agent) | Inputs | Done when |
   |---|------|---------------|--------|-----------|

   Assign each task to a specialist from `.claude/agents/`. If a needed specialist does
   not exist, note "→ /forge-agent: <role>".

4. **Sequence** — Mark independent tasks (parallelizable) vs. dependent ones. Identify the
   critical path.

5. **Risks** — Top 3 risks/unknowns and how to de-risk each early.

6. **Gate** — State exactly how the finished work will be verified (which `/quality-gate`
   checks apply).

End with **"Recommended first move"** — the single next action. Give one plan, not a menu.

For large or especially ambiguous work, delegate this analysis to the
`orchestrator-planner` agent and integrate its plan.
