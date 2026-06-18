---
name: forge-agent
description: Scaffold a new specialist subagent in the AAWS house format. Use when a task needs domain expertise no existing agent covers, so the system can grow to cover all fields. Enforces I/O contracts and adversarial inspection compatibility.
argument-hint: "[role / domain for the new specialist]"
---

# Forge Agent

Create a new specialist subagent for: **$ARGUMENTS**

Existing specialists (avoid duplicating these):

!`ls .claude/agents/ 2>/dev/null`

---

## Step 1 — Confirm the Gap

State the specialist's domain, the kinds of tasks it owns, and what it does NOT do (its
boundary vs. neighboring agents). If an existing agent already covers this, stop and
recommend that one instead.

## Step 2 — Define Configuration

- `name`: lowercase-hyphenated, descriptive (e.g., `mobile-engineer`).
- `description`: written for *automatic delegation* — start with the role, then
  "Use for …" listing concrete trigger tasks.
- `tools`: least privilege. Read-only reviewers: `Read, Grep, Glob, Bash`. Agents that
  change code add `Edit, Write`. Add `WebSearch, WebFetch` only if research is core.
- `model`: `opus` for deep reasoning/review/architecture; `sonnet` for implementation.
- `color`: pick an unused, fitting color.

## Step 3 — Define I/O Contracts (MANDATORY)

Every agent MUST declare explicit contracts. Follow this template:

```markdown
**Input contract:** [What the Orchestrator sends: task description + scoped context
(which files/outputs, NOT "read everything") + acceptance criteria + output format.]

**Output contract:**
\```
{ [structured fields matching the agent's deliverable],
  confidence: HIGH|MEDIUM|LOW }
\```
```

The output contract must be specific enough that:
1. The Orchestrator knows exactly what to expect back.
2. The Inspector can verify the output against the contract.
3. Two invocations with the same input produce the same output structure.

## Step 4 — Write the Body

Follow the house style of existing agents:
- One-line identity statement
- "When invoked:" followed by 5 numbered steps encoding how a top expert in this field
  actually works
- Closing line about reporting expectations

The 5 steps must encode *domain expertise*, not generic instructions. "Implement
carefully" is not expertise. "Validate schema migrations are reversible by checking for
DROP COLUMN in the down migration" is expertise.

## Step 5 — Create and Register

1. Create the file at `.claude/agents/<name>.md` with YAML frontmatter + body.
2. Add a row to the roster table in `CLAUDE.md` §3.
3. Verify: confirm the new agent has both input and output contracts, and that its
   `description` field enables accurate automatic routing.

Keep it focused and consistent with the other agents. One specialist, one clear domain.
