# Getting Started with AAWS

This repo *is* the Artemis Agent Work System. Open it in Claude Code and the system loads
automatically: `CLAUDE.md` becomes the operating constitution, the specialists in
`.claude/agents/` become available for delegation, the skills in `.claude/skills/` become
slash commands, and the path-scoped rules activate when you touch matching files.

## 1. One-time setup (optional but recommended)

Activate the safety guardrails and pre-approved permissions by copying the template:

```bash
cp docs/settings.example.json .claude/settings.json
chmod +x .claude/hooks/*.sh
```

Review `.claude/settings.json` first and adjust the `allow`/`deny` lists to your project.
Nothing in the template runs until you copy it into place — this keeps you in control of
what the agent is pre-authorized to do.

> Note: the template is provided rather than auto-installed on purpose. Granting an agent
> standing permissions is a decision you should make explicitly.

## 2. Daily use — the loop

For anything non-trivial, drive the core loop:

```
/plan-work <your goal>      → get a framed plan with task→owner assignments
                            → (Orchestrator delegates to specialists)
/quality-gate               → verify by evidence before declaring done
/ship                       → commit in house style (push/PR only if you ask)
```

For a quick, single-step task you already know how to do, just ask directly — delegation
is for research-heavy, multi-file, or parallelizable work.

## 3. The specialists

Delegation is automatic: describe a task and the Orchestrator routes it to the right
specialist based on each agent's `description`. You can also request one explicitly, e.g.
"have the **security-auditor** review the auth changes."

| Agent | Owns |
|---|---|
| `orchestrator-planner` | Decomposing large/ambiguous work into a plan |
| `solution-architect` | Architecture, trade-offs, design docs |
| `deep-researcher` | Multi-source, cited investigation |
| `backend-engineer` | APIs, services, data, business logic |
| `frontend-engineer` | UI, components, client state, a11y |
| `devops-engineer` | CI/CD, IaC, containers, deploys, observability |
| `data-scientist` | Analysis, modeling, evaluation, pipelines |
| `security-auditor` | Threat modeling, vuln review, hardening |
| `qa-test-engineer` | Test strategy and authoring |
| `code-reviewer` | Diff review for bugs and cleanup |
| `debugger` | Root-cause analysis of failures |
| `technical-writer` | Docs, guides, explanations |

## 4. Extending the system to new fields

When work needs expertise no specialist covers:

```
/forge-agent <role>     → scaffolds a new specialist in the house format and
                          registers it in CLAUDE.md
/forge-skill <workflow> → captures a repeatable workflow as a new /command
```

This is the mechanism by which AAWS reaches "all fields": every gap you hit becomes a
permanent capability of the system.

## 5. Where things live

```
CLAUDE.md                     # constitution (loads every session)
docs/ARCHITECTURE.md          # full design
docs/GETTING_STARTED.md       # this file
docs/settings.example.json    # opt-in permissions + hooks template
.claude/
  agents/                     # specialist subagents
  skills/                     # workflow playbooks (/commands)
  rules/                      # path-scoped guidance
  hooks/                      # safety scripts (inert until wired in settings)
```

## 6. Customizing

- **Project facts** the agent should always know → add to `CLAUDE.md`.
- **Path-specific conventions** (e.g. a particular module's rules) → add a file in
  `.claude/rules/` with a `paths:` glob.
- **Personal, uncommitted notes** → `CLAUDE.local.md` (gitignored).
- **Tune a specialist** → edit its file in `.claude/agents/`.

Keep everything in the established house style so the system stays coherent as it grows.
