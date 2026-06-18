# Artemis Agent Work System (AAWS)

> A top-tier, multi-domain **agent work system** built entirely on Claude Code's native
> extensibility — turning Claude Code into a coordinated team of senior specialists that
> can take on work in any field.

AAWS is not an external framework or runtime. It's a disciplined arrangement of Claude
Code's own features — memory, subagents, skills, path-scoped rules, and hooks — assembled
into one coherent operating model.

## What it gives you

- **An operating model:** *Orchestrate → Delegate → Verify.* The main thread plans work,
  routes each part to the right specialist, integrates the results, and enforces a quality
  bar. (`CLAUDE.md`)
- **A specialist roster:** 12 domain experts — architecture, research, backend, frontend,
  devops, data/ML, security, QA, review, debugging, docs, and planning. (`.claude/agents/`)
- **Workflow playbooks** as slash commands: `/plan-work`, `/quality-gate`, `/ship`, plus
  self-extension forges. (`.claude/skills/`)
- **Path-scoped rules** that auto-load only when relevant files are touched.
  (`.claude/rules/`)
- **Opt-in guardrails:** destructive-command guard + session orientation banner.
  (`.claude/hooks/`, enabled via `docs/settings.example.json`)
- **Self-extension:** `/forge-agent` and `/forge-skill` grow the system to cover any field
  you use it in — every gap becomes a permanent capability.

## Quick start

Open this repo in Claude Code — the system loads automatically. Then:

```
/plan-work <your goal>      # frame the work and assign owners
/quality-gate               # verify by evidence before declaring done
/ship                       # commit in house style (push/PR only if you ask)
```

Optionally activate the safety hooks and pre-approved permissions:

```bash
cp docs/settings.example.json .claude/settings.json   # review before activating
chmod +x .claude/hooks/*.sh
```

## Learn more

- **`docs/ARCHITECTURE.md`** — the full design and the five layers.
- **`docs/GETTING_STARTED.md`** — how to use and extend the system.
- **`CLAUDE.md`** — the operating constitution that loads every session.

## Extending to new fields

When a task needs expertise no specialist covers, mint one:

```
/forge-agent <role>      # scaffold a new specialist in the house format
/forge-skill <workflow>  # capture a repeatable workflow as a new /command
```

This is how AAWS reaches "all fields": it broadens toward whatever domain it's put to work
on, and the new capability persists for next time.

---

<sub>原 "artemis · 第一个仓库" 已升级为 Artemis Agent Work System。</sub>
