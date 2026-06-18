---
name: plan-work
description: Classify topology, then turn a goal into a framed, owner-assigned task plan with scoped context briefs and I/O contracts for every handoff. Use at the start of any non-trivial or multi-domain piece of work.
argument-hint: "[goal or task description]"
---

# Plan Work

Produce an execution plan for: **$ARGUMENTS**

This is the system's planning gateway. Every non-trivial task passes through here before
implementation begins. The plan MUST include topology classification, context scoping, and
handoff contracts — not just a task list.

---

## Step 1 — Classify Topology (MANDATORY — do this first)

Analyze the task's structural properties and select the coordination pattern:

| Topology | Select when | Pattern |
|---|---|---|
| **SOLO** | Single well-scoped action with no dependencies | Do it yourself. Skip delegation. |
| **SEQUENTIAL** | Steps with strict dependencies: A must finish before B starts | Chain agents in order. Each receives the prior's output. |
| **PARALLEL-FANOUT** | Independent subtasks that can run concurrently + synthesis | Dispatch agents in parallel. Synthesize outputs after. |
| **HIERARCHICAL** | Large scope needing nested orchestration or sub-teams | Delegate sub-planning to `orchestrator-planner`, then dispatch. |

**Classification output:**
```
Topology: [SOLO | SEQUENTIAL | PARALLEL-FANOUT | HIERARCHICAL]
Rationale: [one line — why this topology fits]
```

**If uncertain, default to SEQUENTIAL.** It is the safest — dependencies are respected
even if the classification is wrong. Never default to PARALLEL-FANOUT when uncertain;
undetected dependencies break parallel execution silently.

If SOLO: state the action, skip the rest of this plan, and execute directly.

---

## Step 2 — Frame

Restate the goal, success criteria, and hard constraints in 2–4 lines.
List assumptions you are making to resolve ambiguity.

---

## Step 3 — Survey

Read only what you need to plan accurately: `CLAUDE.md`, `README`, the directories
the work touches. Note existing patterns to reuse. Do not over-read.

---

## Step 4 — Decompose with Contracts

Produce a task table. Each task MUST specify:

| # | Task | Owner | Context Brief | Input → Output Contract | Depends On | Done When |
|---|------|-------|---------------|------------------------|------------|-----------|
| 1 | ... | `agent-name` | Files: X, Y; Exclude: Z | Receives: diff; Returns: {findings} | — | ... |
| 2 | ... | `agent-name` | Prior output from #1 | Receives: fix plan; Returns: {changes} | #1 | ... |

**Context Brief** — what files/outputs this agent needs, and what to EXCLUDE. This is
not optional. "Read the whole repo" is never a valid context brief.

**Input → Output Contract** — match the contracts declared in the agent's definition.
If the agent's output contract says `{ findings: [{severity, file, line, issue, fix}] }`,
that is what the Orchestrator should expect.

Assign each task to a specialist from `.claude/agents/`. If a needed specialist does
not exist, note "→ /forge-agent: <role>" and describe the gap.

---

## Step 5 — Sequence per Topology

Align the task sequence with the classified topology:

- **SEQUENTIAL:** strict chain, each step depends on the previous.
- **PARALLEL-FANOUT:** group independent tasks in parallel batches, then add a
  synthesis task. Mark parallel groups clearly: `[P1: #2, #3, #4] → #5 (synthesis)`.
- **HIERARCHICAL:** identify which tasks are sub-plans that need their own
  orchestrator-planner invocation.

Identify the **critical path** — the longest dependency chain.

---

## Step 6 — Risks

Top 3 risks/unknowns. For each: the risk, its likelihood, its impact if it hits, and
the mitigation (how to de-risk it early, before it becomes expensive).

---

## Step 7 — Verification Gate

State exactly how the finished work will be verified:
- Which `/quality-gate` checks apply?
- Does the work warrant `/critical-decision` (high-stakes, irreversible)?
- What Inspector mandate should be used? (correctness? security? specification compliance?)
- What constitutes PASS?

---

## Output

End with **"Recommended first move"** — the single next action.

For large or especially ambiguous work, delegate this entire analysis to the
`orchestrator-planner` agent (which has topology classification built into its process)
and integrate its plan.
