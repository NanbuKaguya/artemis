---
name: forge-agent
description: Scaffold a new specialist subagent in the Artemis house format. Use when a task needs domain expertise no existing agent covers, so the system can grow to cover all fields.
argument-hint: "[role / domain for the new specialist]"
---

# Forge Agent

Create a new specialist subagent for: **$ARGUMENTS**

Existing specialists (avoid duplicating these):

!`ls .claude/agents/ 2>/dev/null`

Steps:

1. **Define the niche.** State the specialist's domain, the kinds of tasks it owns, and —
   importantly — what it does NOT do (its boundary vs. neighboring agents). If an existing
   agent already covers this, stop and recommend that one instead.

2. **Choose configuration:**
   - `name`: lowercase-hyphenated, descriptive (e.g., `mobile-engineer`).
   - `description`: written for *automatic delegation* — start with the role, then
     "Use for …" listing concrete trigger tasks. This is how the Orchestrator routes to it.
   - `tools`: least privilege. Read-only reviewers get `Read, Grep, Glob, Bash`; agents
     that change code add `Edit, Write`. Add `WebSearch, WebFetch` only if research is core.
   - `model`: `opus` for deep reasoning/review/architecture; `sonnet` for implementation.
   - `color`: pick an unused, fitting color.

3. **Write the body** in the house style of the existing agents: a one-line identity, then
   a numbered "When invoked" operating procedure (≈5 steps) encoding how a top expert in
   this field actually works, ending with reporting/quality expectations.

4. **Create the file** at `.claude/agents/<name>.md` with YAML frontmatter + body.

5. **Register it** — add a row to the roster table in `CLAUDE.md` so the Orchestrator
   knows it exists.

Keep it focused and consistent with the other agents. One specialist, one clear domain.
