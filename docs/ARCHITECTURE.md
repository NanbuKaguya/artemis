# AAWS Architecture — v2

The Artemis Agent Work System is an operating model built entirely on Claude Code's
native extensibility. There is no external runtime. The system is a disciplined
arrangement of memory, subagents, skills, rules, and hooks that makes Claude Code
behave like a coordinated team of senior specialists with structural verification.

## Design Principles

1. **Harness over model.** 98.4% of an agentic system's value is infrastructure:
   routing, contracts, verification, context management. The model is table stakes;
   the harness is the differentiator.
   *(Source: arXiv:2604.14228 — reverse engineering of Claude Code architecture)*

2. **Specification quality is the highest-leverage investment.** 41.8% of multi-agent
   failures are specification/coordination problems. Every handoff has an explicit I/O
   contract. Free-form delegation is the system's dominant failure mode.
   *(Source: arXiv:2503.13657 — MAST failure taxonomy, 1,642 traces)*

3. **Verification must be structurally separated from generation.** An agent reviewing
   its own output in the same context is ineffective. The Inspector receives only the
   artifact, never the context that produced it.
   *(Source: ICML 2025 Inspector pattern — 96.4% error interception)*

4. **Topology selection is a first-class decision.** Different tasks need different
   coordination patterns. Fixed hub-and-spoke costs 12–23% vs. dynamic topology.
   *(Source: arXiv:2602.16873 — AdaptOrch)*

5. **Systems must learn from experience.** Reflexion: storing verbal self-critiques
   after failures yields +11pp on HumanEval. Removing the critique step eliminates all
   gain. The verbal reflection is load-bearing.
   *(Source: arXiv:2303.11366 — Reflexion)*

6. **Use multi-agent selectively, not by default.** Under equal token budgets, single
   agents outperform multi-agent on multi-hop reasoning. Multi-agent is justified when
   task structure demands parallel execution, adversarial verification, or domain depth.
   *(Source: arXiv:2604.02460)*

## The Six Layers

```
┌───────────────────────────────────────────────────────────────────┐
│ 1. CONSTITUTION  — CLAUDE.md                                      │
│    Core loop (Classify → Orchestrate → Inspect → Learn), topology │
│    table, memory architecture, quality bar, conventions.          │
├───────────────────────────────────────────────────────────────────┤
│ 2. SPECIALISTS  — .claude/agents/*.md                             │
│    16 domain experts + meta-agents. Each has explicit I/O         │
│    contracts. Tools are least-privilege. Opus for reasoning,      │
│    sonnet for implementation.                                     │
├───────────────────────────────────────────────────────────────────┤
│ 3. PLAYBOOKS  — .claude/skills/<name>/SKILL.md                    │
│    Topology-aware planning, adversarial quality gate, structured  │
│    debate, episodic reflection, self-extension forges.            │
├───────────────────────────────────────────────────────────────────┤
│ 4. MEMORY  — four-tier CoALA model                                │
│    Working (context) → Episodic (.claude/memory/episodes/) →      │
│    Semantic (CLAUDE.md, .claude/rules/) →                         │
│    Procedural (.claude/skills/, .claude/agents/)                  │
├───────────────────────────────────────────────────────────────────┤
│ 5. RULES  — .claude/rules/*.md                                    │
│    Path-scoped guidance that auto-loads when matching files are    │
│    active. Handoff contract standard, episode format, engineering  │
│    baseline, testing rules.                                       │
├───────────────────────────────────────────────────────────────────┤
│ 6. GUARDRAILS  — .claude/hooks/*.sh + settings template           │
│    Destructive-command guard, session banner. Opt-in via template. │
└───────────────────────────────────────────────────────────────────┘
```

## The Core Loop

```
User goal
   │
   ▼
[Classify Topology] ── SOLO → do it yourself
   │                    SEQUENTIAL / PARALLEL / HIERARCHICAL ↓
   ▼
[Plan with Contracts] ── /plan-work or orchestrator-planner
   │                     Each task: owner + context brief + I/O contract
   │
   ├─▶ Agent: specialist-A  ─┐
   ├─▶ Agent: specialist-B   ├─ per classified topology
   ├─▶ Agent: specialist-C  ─┘
   │
   ▼
[Inspect Adversarially] ── /quality-gate
   │                        Inspector: fresh context, artifact-only, opposing mandate
   │                        High-stakes? → /critical-decision (proponent + skeptic + judge)
   │
   ▼
[Learn] ── write episode to .claude/memory/episodes/
   │        periodically /reflect → distill to .claude/rules/
   │
   ▼
[Report / Ship]
```

## What Makes This Architecture Surpass Standard Approaches

| Dimension | Standard (v1 / most frameworks) | AAWS v2 | Mechanism |
|---|---|---|---|
| Topology | Fixed hub-and-spoke | Dynamic per-task classification | §1.2 of CLAUDE.md |
| Verification | Same-context self-review | Structurally separated Inspector with adversarial mandate | Inspector agent + /quality-gate |
| High-stakes | Single reviewer | Courtroom-style structured debate (proponent, skeptic, judge) | /critical-decision |
| Handoffs | Free-form descriptions | Explicit I/O contracts on every agent | handoff-contracts rule + agent frontmatter |
| Context | Dump everything | Scoped per agent via context briefs | Plan step §1.3 of CLAUDE.md |
| Memory | Stateless (reset each session) | Four-tier CoALA: working, episodic, semantic, procedural | §2 of CLAUDE.md + /reflect |
| Learning | None | Episodic → distillation → rules/skills | /reflect skill |
| Self-extension | Mint more static agents | Mint agents with contracts; improve via evidence | /forge-agent + /reflect |

## Specialist Roster

16 agents in `.claude/agents/`:

**Domain specialists** (12): orchestrator-planner, solution-architect, deep-researcher,
backend-engineer, frontend-engineer, devops-engineer, data-scientist, security-auditor,
qa-test-engineer, code-reviewer, debugger, technical-writer.

**Meta-agents** (4): inspector (adversarial verification), consensus-judge (arbitration),
proponent (advocacy in debate), skeptic (challenge in debate).

## Evidence Base

This architecture is designed against empirical findings, not intuition:

- AdaptOrch (arXiv:2602.16873) — topology-aware routing: 12–23% improvement
- MAST (arXiv:2503.13657) — 41.8% of failures from specification problems
- Inspector pattern (ICML 2025) — 96.4% error interception with structural separation
- Reflexion (arXiv:2303.11366) — +11pp HumanEval from verbal self-critique
- Six Sigma Agent (arXiv:2601.22290) — mathematical reliability via consensus
- PROClaim (arXiv:2603.28488) — courtroom-style debate for verification
- MAST single-agent finding (arXiv:2604.02460) — multi-agent not always better
- Claude Code analysis (arXiv:2604.14228) — 98.4% infrastructure, 1.6% AI logic
- Anthropic's multi-agent system — 90.2% improvement, failure from vague delegation
- Council Mode (arXiv:2604.02923) — 35.9% hallucination reduction via multi-model consensus

See `GETTING_STARTED.md` for usage instructions.
