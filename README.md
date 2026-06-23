# Artemis

A world-class AI work system built on Claude Code's native primitives. Not an orchestration framework — a context engineering system that makes every session better than the last.

## What it is

Artemis configures Claude Code to operate at its theoretical ceiling:

- **The right loop:** CLARIFY → ANCHOR → BUILD → VERIFY → LEARN. Each step is justified by empirical research on where agent systems fail.
- **Minimal instruction surface:** CLAUDE.md at ~500 tokens. Every line changes Claude's defaults. Bloat causes instruction ignoring.
- **Deterministic enforcement:** Hooks for hard requirements, not prose. The guards run; they don't ask nicely.
- **Adversarial verification:** Inspector agent operates in fresh context, artifact only. Same mechanism responsible for 96.4% error interception in the ICML 2025 Inspector pattern.
- **Self-improvement:** Episodic memory → `/reflect` → distilled rules. The system gets better through experience, not through manual updates.

## Quick start

Open this repo in Claude Code. The system loads automatically.

```
/quality-gate     # verify before shipping
/reflect          # distill episodes into rules (every 5-10 episodes)
```

The loop runs automatically on every non-trivial task.

## What's here

```
CLAUDE.md                          # The operating loop — loads every session
.claude/
  agents/
    inspector.md                   # Adversarial artifact review (fresh context)
    researcher.md                  # Multi-source investigation (context isolation)
    reviewer.md                    # Code diff review (cold read)
  skills/
    quality-gate/                  # Deterministic + adversarial verification
    reflect/                       # Episode → rule distillation
  rules/
    spec-anchor.md                 # Prevents specification drift
    handoff-contracts.md           # Delegation format
    episode-format.md              # Episode structure
    learned.md                     # Accumulated rules (800 token budget)
  hooks/
    guard-destructive.sh           # Blocks dangerous commands (opt-in)
    session-banner.sh              # Orientation + memory status (opt-in)
  memory/
    episodes/                      # Raw experience records
docs/
  ARCHITECTURE.md                  # Design decisions + evidence base
```

## The self-improvement loop

```
Task → Episode (failure/surprise) → /reflect → learned.md → Better next session
```

After 5–10 episodes, run `/reflect`. It distills high-signal patterns into rules, prunes what didn't hold, and keeps the rule base under 800 tokens. The system compounds — each session starts from a better baseline than the last.

## Evidence base

| Decision | Source |
|---|---|
| ~500 token CLAUDE.md | Claude Code docs: bloated files cause instruction ignoring |
| 3 agents, not 16 | arXiv:2511.00872: multi-agent coordination degrades coding 2-15% |
| Inspector: artifact only | ICML 2025: 96.4% error interception from structural separation |
| Hooks for hard requirements | Anthropic + OpenAI: deterministic > advisory |
| Spec anchoring | arXiv:2603.17104: recovers 90% of spec faithfulness loss |
| Episodic memory + reflect | arXiv:2303.11366: +11pp from verbal self-critique |
| Clarify before executing | arXiv:2503.13657: spec ambiguity = 41.8% of failures |
