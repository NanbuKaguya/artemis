# Getting Started with Artemis

Open this repo in Claude Code. The system loads automatically.

## Quick Start

```
/quality-gate     # verify before shipping
/reflect          # distill episodes into rules (every 5-10 episodes)
```

That's it. The operating loop runs automatically on every non-trivial task.

## The Loop

Every task follows this sequence:

```
CLARIFY → ANCHOR → BUILD → VERIFY → LEARN
```

**CLARIFY** — Spec ambiguous in ways that change the approach? Ask first.  
**ANCHOR** — Touching multiple files or hard to reverse? Write `.spec-anchor`.  
**BUILD** — Smallest correct change. Match surrounding patterns.  
**VERIFY** — Tests → lint → type check → Inspector (if non-trivial).  
**LEARN** — Failure or surprise? Write an episode. 5–10 episodes? Run `/reflect`.

## The Agents (3, not 16)

| Agent | When | What it gets |
|---|---|---|
| `inspector` | After any non-trivial generation | Artifact only. No context. |
| `researcher` | 3+ sources needed, 5+ unfamiliar files | The question only. |
| `reviewer` | Before shipping a significant diff | The diff only. |

The default is: **do it yourself**. Delegation costs context and latency. Justify it.

## The Two-Layer Architecture

```
CLAUDE.md     — Behavioral layer: HOW Claude works
AGENTS.md     — Context layer: WHAT this project is
```

For your own projects: put the operating loop in CLAUDE.md (or let Artemis handle it), and put project-specific context in AGENTS.md at the project root.

## Where Things Live

```
CLAUDE.md                          # Operating loop (loads every session)
AGENTS.md                          # Project context layer
.claude/
  agents/                          # inspector · researcher · reviewer
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
  ARCHITECTURE.md                  # Design decisions with evidence base
```

## Activating Optional Guardrails

```bash
cp docs/settings.example.json .claude/settings.json
chmod +x .claude/hooks/*.sh
```

Review the template before copying — nothing runs until it's in place.

## The Self-Improvement Loop

```
Task → Episode (failure/surprise) → /reflect → learned.md → Better next session
```

After 5–10 episodes, run `/reflect`. It distills high-signal patterns into rules, prunes what didn't hold, and keeps the rule base under 800 tokens. The system compounds — each session starts from a better baseline than the last.
