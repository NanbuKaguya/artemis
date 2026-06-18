---
name: forge-skill
description: Scaffold a new skill playbook in the Artemis house format. Use to capture a repeatable workflow so it can be invoked consistently with a slash command.
argument-hint: "[workflow to capture]"
---

# Forge Skill

Create a new skill playbook for: **$ARGUMENTS**

Existing skills (avoid duplicating these):

!`ls .claude/skills/ 2>/dev/null`

Steps:

1. **Confirm it's a procedure.** Skills capture *repeatable workflows*. If this is a
   durable fact, it belongs in `CLAUDE.md`; if it's path-specific guidance, it belongs in
   `.claude/rules/`. Only proceed if it's a procedure worth invoking by name.

2. **Choose configuration:**
   - directory name = the invocation (`/<name>`); lowercase-hyphenated.
   - `description`: when Claude/you should reach for it (drives auto-discovery).
   - `argument-hint`: what the user passes, if anything.
   - `allowed-tools`: restrict if the workflow should only touch certain tools.
   - Set `disable-model-invocation: true` if only a human should run it (e.g. deploys).

3. **Write the body** as a clear, ordered procedure. Use `$ARGUMENTS` / `$1` for inputs
   and `` !`command` `` to inject live context (e.g. `git status`). Keep `SKILL.md` tight;
   move long reference material into sibling files in the skill directory.

4. **Create the file** at `.claude/skills/<name>/SKILL.md`.

5. **Register it** — if it's a top-level workflow, add it to the skills list in `CLAUDE.md`
   and `docs/GETTING_STARTED.md`.

Match the style of the existing skills. One workflow, clearly executable, end to end.
