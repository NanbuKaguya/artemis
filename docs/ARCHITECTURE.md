# AAWS Architecture

The Artemis Agent Work System (AAWS) is an operating model built entirely on Claude Code's
native extensibility. There is no external runtime — the "system" is a disciplined
arrangement of memory, subagents, skills, rules, and hooks that together make Claude Code
behave like a coordinated team of senior specialists.

## Design goals

1. **Top-tier output in every field** — domain depth comes from specialist subagents, each
   encoding how an expert in that field actually works.
2. **Scales to all fields** — when a domain isn't covered, the system mints a new
   specialist (`/forge-agent`) in a consistent house format. Coverage grows over time.
3. **Quality is enforced, not hoped for** — a verification gate and review specialists sit
   between "implemented" and "done."
4. **Lean context** — the main thread orchestrates and delegates; specialists absorb the
   heavy reading so the primary conversation stays sharp.
5. **Safe by default** — least-privilege tools, destructive-command guards, and explicit
   confirmation for irreversible actions.

## The five layers

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. CONSTITUTION  — CLAUDE.md                                       │
│    Operating model (Orchestrate→Delegate→Verify), roster, quality  │
│    bar, conventions. Loads every session.                          │
├──────────────────────────────────────────────────────────────────┤
│ 2. SPECIALISTS  — .claude/agents/*.md                              │
│    Domain experts the Orchestrator delegates to. Routed by their   │
│    `description`. Least-privilege tools; opus for reasoning, sonnet │
│    for implementation.                                             │
├──────────────────────────────────────────────────────────────────┤
│ 3. PLAYBOOKS  — .claude/skills/<name>/SKILL.md                     │
│    Repeatable workflows invoked as /commands: plan, gate, ship,    │
│    and the self-extension forges.                                  │
├──────────────────────────────────────────────────────────────────┤
│ 4. RULES  — .claude/rules/*.md                                     │
│    Path-scoped guidance that auto-loads only when matching files   │
│    are in play (source baseline, testing rules).                   │
├──────────────────────────────────────────────────────────────────┤
│ 5. GUARDRAILS  — .claude/hooks/*.sh + settings (opt-in template)   │
│    Deterministic safety: destructive-command guard, session        │
│    orientation banner.                                             │
└──────────────────────────────────────────────────────────────────┘
```

## The core loop: Orchestrate → Delegate → Verify

The main thread is the **Orchestrator**. For non-trivial work it:

1. **Frames** the goal and success criteria.
2. **Plans** with `/plan-work` (or the `orchestrator-planner` agent for big/ambiguous work).
3. **Delegates** each task to the owning specialist via the `Agent` tool — independent
   tasks in parallel.
4. **Integrates** specialist results into one coherent thread.
5. **Verifies** with `/quality-gate` (pulling in `code-reviewer` / `security-auditor`).
6. **Reports** outcomes faithfully and, if asked, ships with `/ship`.

```
User goal
   │
   ▼
[Orchestrator] ── /plan-work ──▶ framed plan with task→owner mapping
   │
   ├─▶ Agent: backend-engineer   ─┐
   ├─▶ Agent: frontend-engineer   ├─ parallel where independent
   ├─▶ Agent: deep-researcher    ─┘
   │
   ▼
[Integrate] ──▶ /quality-gate ──▶ code-reviewer / security-auditor
   │
   ▼
[Report] ──▶ /ship (only when asked)
```

## Why subagents (not one mega-prompt)

- **Focus** — a specialist's whole context is its domain, so it reasons deeper.
- **Isolation** — each runs in its own context window; the main thread keeps only the
  conclusion, not the file dumps.
- **Parallelism** — independent specialists run concurrently.
- **Least privilege** — reviewers and auditors are read-only by tool restriction.

## Self-extension (reaching "all fields")

The system is designed to grow. `/forge-agent` and `/forge-skill` scaffold new specialists
and playbooks in the exact house format and register them in `CLAUDE.md`. A gap discovered
during work becomes a permanent capability, so AAWS broadens toward any field it's used in.

See `GETTING_STARTED.md` for how to use and extend the system.
