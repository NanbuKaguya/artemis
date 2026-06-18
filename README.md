# Artemis Agent Work System (AAWS) — v2

> A **top-tier agent work system** built on Claude Code's native features, designed to
> surpass standard multi-agent frameworks by addressing the empirically proven failure
> modes that make most agent systems mediocre.

AAWS is not an external framework. It's a disciplined arrangement of Claude Code's own
features — subagents, skills, memory, rules, and hooks — assembled into an operating
model grounded in current research (AdaptOrch, MAST, Reflexion, Inspector pattern).

## What makes it different

Most multi-agent systems fail because of specification ambiguity (41.8%), coordination
breakdown (36.9%), and verification gaps (21.3%) — not model capability. AAWS addresses
each of these structurally:

- **Topology-aware orchestration.** Tasks are classified (SOLO / SEQUENTIAL / PARALLEL /
  HIERARCHICAL) before delegation, matching the coordination pattern to the task structure
  instead of using one-size-fits-all hub-and-spoke.
- **Structurally adversarial verification.** The Inspector agent reviews artifacts in a
  fresh context with an opposing mandate — never same-context self-review. For high-stakes
  decisions, structured debate (proponent + skeptic + judge).
- **Explicit I/O contracts on every handoff.** Every agent declares what it receives and
  returns. No free-form delegation.
- **Four-tier memory (CoALA model).** Working + Episodic + Semantic + Procedural. The
  system learns from experience via `/reflect`, which distills episodes into rules.
- **16 specialists + self-extension.** 12 domain experts, 4 meta-agents (inspector, judge,
  proponent, skeptic). `/forge-agent` mints new specialists with contracts when gaps appear.

## Quick start

Open this repo in Claude Code — the system loads automatically.

```
/plan-work <goal>              # classify topology → contracted task plan
/quality-gate                  # adversarial inspection pipeline
/critical-decision <artifact>  # structured debate for high-stakes
/reflect                       # distill experience into rules
/ship                          # commit in house style
```

## Evidence base

The architecture is designed against empirical findings:

| Finding | Source | How AAWS addresses it |
|---|---|---|
| 41.8% of multi-agent failures = specification problems | MAST (arXiv:2503.13657) | Explicit I/O contracts on every handoff |
| 96.4% error interception with structural separation | ICML 2025 Inspector pattern | Inspector agent: fresh context, artifact-only |
| 12–23% gain from dynamic topology routing | AdaptOrch (arXiv:2602.16873) | Mandatory topology classification before planning |
| +11pp from verbal self-critique stored as memory | Reflexion (arXiv:2303.11366) | Episodic memory + /reflect distillation |
| Multi-agent debate fails under sycophancy | arXiv:2509.05396 | Strict isolation: proponent/skeptic never see each other |
| 98.4% of agentic system value is infrastructure | arXiv:2604.14228 | Contracts, rules, hooks — not just agent prompts |

## Learn more

- **`docs/ARCHITECTURE.md`** — full design, six layers, evidence base
- **`docs/GETTING_STARTED.md`** — usage, specialist roster, file map
- **`CLAUDE.md`** — the operating constitution loaded every session
