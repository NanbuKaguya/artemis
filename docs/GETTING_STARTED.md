# Getting Started with AAWS v2

Open this repo in Claude Code and the system loads automatically. `CLAUDE.md` becomes
the operating constitution, specialists become available for delegation, skills become
slash commands, and path-scoped rules activate when you touch matching files.

## Quick Start

For any non-trivial task:

```
/plan-work <your goal>      → classify topology, build contracted task plan
                            → orchestrator delegates to specialists per topology
/quality-gate               → adversarial inspection (Inspector in fresh context)
/ship                       → commit in house style (push/PR only if you ask)
```

For high-stakes decisions:

```
/critical-decision <artifact>  → proponent + skeptic + judge structured debate
```

For system learning:

```
/reflect                    → distill episodes into rules, prune low-signal
```

## The Core Loop

Every non-trivial request follows this sequence:

1. **Classify topology** — SOLO / SEQUENTIAL / PARALLEL-FANOUT / HIERARCHICAL
2. **Plan with contracts** — each task gets an owner, context brief, and I/O contract
3. **Delegate per topology** — parallel for independent tasks, sequential for dependent
4. **Inspect adversarially** — Inspector in fresh context with artifact-only input
5. **Learn** — write episode for failures/surprises; `/reflect` to distill

## The Specialists (16 agents)

| Agent | Domain | Model |
|---|---|---|
| `orchestrator-planner` | Strategy, decomposition, topology classification | opus |
| `solution-architect` | System design, trade-offs, design docs | opus |
| `deep-researcher` | Multi-source investigation, cited findings | sonnet |
| `backend-engineer` | APIs, services, databases, business logic | sonnet |
| `frontend-engineer` | UI, components, client state, accessibility | sonnet |
| `devops-engineer` | CI/CD, IaC, containers, deployment | sonnet |
| `data-scientist` | Analysis, modeling, evaluation, pipelines | sonnet |
| `security-auditor` | Threat modeling, vuln review, hardening | opus |
| `qa-test-engineer` | Test strategy, test authoring, coverage | sonnet |
| `code-reviewer` | Diff review for correctness and cleanup | opus |
| `debugger` | Root-cause analysis of failures | opus |
| `technical-writer` | Docs, guides, explanations | sonnet |
| `inspector` | Adversarial artifact verification | opus |
| `consensus-judge` | Multi-agent arbitration | opus |
| `proponent` | Advocate FOR in structured debate | sonnet |
| `skeptic` | Advocate AGAINST in structured debate | sonnet |

## Memory Architecture

Four tiers, each with a distinct role:

- **Working** — current context window (ephemeral)
- **Episodic** — `.claude/memory/episodes/` — records of past work with lessons learned
- **Semantic** — `CLAUDE.md`, `.claude/rules/` — distilled facts and conventions
- **Procedural** — `.claude/skills/`, `.claude/agents/` — executable workflows

Memory flows upward: episodes are raw evidence → `/reflect` distills them into rules
and skill improvements → the system gets better at its job over time.

## Extending the System

```
/forge-agent <role>      → new specialist with I/O contracts
/forge-skill <workflow>  → new playbook as a slash command
```

Every gap becomes a permanent capability. New agents MUST include I/O contracts.

## Where Things Live

```
CLAUDE.md                          # constitution (loads every session)
.claude/
  agents/                          # 16 specialist subagents with I/O contracts
  skills/
    plan-work/                     # topology-aware planning
    quality-gate/                  # adversarial inspection pipeline
    critical-decision/             # structured debate for high-stakes
    reflect/                       # episodic memory distillation
    ship/                          # commit and deliver
    forge-agent/                   # scaffold new specialists
    forge-skill/                   # scaffold new playbooks
  rules/
    handoff-contracts.md           # standard delegation/response formats
    episode-format.md              # episode record template
    engineering-baseline.md        # source code conventions
    tests.md                       # testing conventions
  memory/
    episodes/                      # episodic memory store
  hooks/
    guard-destructive.sh           # blocks dangerous commands (opt-in)
    session-banner.sh              # session orientation (opt-in)
docs/
  ARCHITECTURE.md                  # full design with evidence base
  GETTING_STARTED.md               # this file
  settings.example.json            # opt-in permissions + hooks template
```

## Activating Optional Guardrails

```bash
cp docs/settings.example.json .claude/settings.json   # review before activating
chmod +x .claude/hooks/*.sh
```

Review the template first. Nothing runs until you copy it into place.
