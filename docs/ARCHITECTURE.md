# Artemis Architecture

Artemis is a context engineering system built on Claude Code's native primitives. It is not an orchestration framework — it is a disciplined configuration that makes Claude Code behave at a higher level in every session.

## Design Philosophy

**The harness is the differentiator, not the model.**
98.4% of Claude Code's codebase is deterministic infrastructure (arXiv:2604.14228). The same principle applies here: model capability is table stakes; how context is structured, verified, and accumulated is the differentiator.

**Simplicity beats complexity for sequential tasks.**
Single-agent configurations match or beat complex multi-agent orchestration on coding tasks (arXiv:2511.00872, arXiv:2601.12307). Artemis uses subagents for two purposes only: context isolation and adversarial verification.

**Deterministic enforcement > instruction.**
Hooks guarantee execution; CLAUDE.md is advisory. Hard requirements live in hooks. Both Anthropic and OpenAI engineering teams independently reached this conclusion.

**Context quality is the primary performance lever.**
Scaffolding accounts for 22+ point swings on SWE-bench; model upgrades account for ~1 point. Bloated instruction files cause instruction ignoring. Every instruction file in Artemis is held to minimum viable size.

**Systems that learn compound over time.**
+11pp on HumanEval from verbal self-critique after failures (Reflexion, arXiv:2303.11366). Episodic memory and distillation are structural, not optional.

## The Four Layers

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. CLAUDE.md  — The operating loop + behavioral constraints     │
│    ~500 tokens. Every line changes Claude's defaults.           │
│    Loop: CLARIFY → ANCHOR → BUILD → VERIFY → LEARN             │
├─────────────────────────────────────────────────────────────────┤
│ 2. Agents  — Context isolation + adversarial review             │
│    inspector: fresh-context adversarial review                  │
│    researcher: search isolation                                 │
│    reviewer: cold diff review                                   │
├─────────────────────────────────────────────────────────────────┤
│ 3. Rules + Skills  — Guidance + accumulated knowledge           │
│    spec-anchor: prevents specification drift                    │
│    learned.md: distilled rules (800 token budget)               │
│    /quality-gate: verification pipeline                         │
│    /reflect: episodic → rules distillation                      │
├─────────────────────────────────────────────────────────────────┤
│ 4. Hooks  — Deterministic enforcement                           │
│    guard-destructive: blocks dangerous commands                 │
│    session-banner: orientation + memory status                  │
└─────────────────────────────────────────────────────────────────┘
```

## The Operating Loop

```
User input
    │
    ▼
CLARIFY — Spec ambiguous in ways that change approach?
    │       Yes → ask before proceeding
    │       No ↓
    ▼
ANCHOR — Multi-file, ambiguous, or hard to reverse?
    │       Yes → write .spec-anchor
    │       No ↓
    ▼
BUILD — Smallest correct change. Match surrounding patterns.
    │
    ▼
VERIFY — Tests/lint/type/secrets → Inspector (artifact only)
    │
    ▼
LEARN — Failure/surprise? → Episode → /reflect every 5-10
```

## Self-Improvement Loop

```
Experience → Episode → /reflect → learned.md → Better next session
```

The 800 token budget on `learned.md` enforces quality over quantity. Rules that don't earn their tokens are pruned. The system stays lean and accurate.

## Evidence Base

| Decision | Evidence | Source |
|---|---|---|
| Short CLAUDE.md | Bloated files cause instruction ignoring | Claude Code docs + field reports |
| 3 agents not 16 | Multi-agent coordination degrades coding 2-15% | arXiv:2511.00872 |
| Inspector: artifact only | 96.4% error interception from structural separation | ICML 2025 Inspector pattern |
| Hooks for hard requirements | Deterministic > advisory for critical constraints | Anthropic + OpenAI engineering |
| Spec anchoring | Recovers 90% of spec faithfulness loss | arXiv:2603.17104 |
| Episodic memory + reflect | +11pp from verbal self-critique | arXiv:2303.11366 |
| Clarify before executing | Spec ambiguity = 41.8% of failures | arXiv:2503.13657 |
