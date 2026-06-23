# Artemis — Project Context

Artemis is a context engineering system for Claude Code. It is not an application; it IS the Claude Code configuration. You are reading this file as both a user of this system and as an example of the pattern it recommends.

## What This Repo Is

A disciplined Claude Code configuration that makes every session better than the last. The differentiator is not the model — it is how context is structured, verified, and accumulated.

## Two-Layer Architecture

```
CLAUDE.md    — Behavioral layer: HOW Claude works (the operating loop)
AGENTS.md    — Context layer: WHAT this project is (this file)
```

Keep these separate. CLAUDE.md stays under 600 tokens. This file carries project context so CLAUDE.md does not have to.

## Key Directories

```
CLAUDE.md                    # Operating loop — loaded every session
AGENTS.md                    # This file — project context
.claude/
  agents/
    inspector.md             # Adversarial artifact review (artifact only, fresh context)
    researcher.md            # Multi-source investigation (context isolation)
    reviewer.md              # Code diff review (cold read)
  skills/
    quality-gate/SKILL.md    # Deterministic + adversarial verification pipeline
    reflect/SKILL.md         # Episode → rule distillation
  rules/
    spec-anchor.md           # Prevents specification drift
    handoff-contracts.md     # Delegation format for subagents
    episode-format.md        # Structure for episodic memory records
    learned.md               # Distilled rules — 800 token hard budget
  hooks/
    guard-destructive.sh     # Blocks dangerous bash commands (opt-in)
    session-banner.sh        # Session orientation + memory status (opt-in)
  memory/
    episodes/                # Raw experience records
docs/
  ARCHITECTURE.md            # Design decisions with evidence base
  GETTING_STARTED.md         # Quick start for new users
  settings.example.json      # Opt-in permissions + hooks template
```

## Change Constraints

- **CLAUDE.md:** Keep under 600 tokens. Every line must change Claude's behavior from its default. No project context in this file.
- **learned.md:** The `/reflect` skill enforces an 800 token hard budget. Do not add rules manually — run `/reflect` instead.
- **Agents (inspector / researcher / reviewer):** These three cover the only valid reasons to delegate: adversarial verification, context isolation, and cold review. Adding agents requires a justification that clears the coordination cost.
- **Hooks:** These are opt-in. Users activate them by copying `docs/settings.example.json` to `.claude/settings.json`. Do not make hooks mandatory.
- **episodes/:** Never delete episode files. `/reflect` archives them after distillation. Let the skill manage the lifecycle.

## The Pattern for Your Own Projects

When you adopt Artemis for a project, create an `AGENTS.md` at that project root:

```markdown
# <Project Name> — Project Context
[What it is, one sentence]

## Architecture
[Where things live, key directories]

## Change Constraints  
[What Claude should know before touching anything]

## Current State
[Active work, open questions, things in progress]
```

Your project's CLAUDE.md stays behavioral (the loop). Your AGENTS.md carries what would otherwise bloat it.
