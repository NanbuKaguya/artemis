---
name: ship
description: Stage, commit in house style, and prepare a change for delivery. Use once work is complete and has passed the quality gate.
argument-hint: "[optional: commit message or summary]"
---

# Ship

Prepare the current work for delivery. Intent: **$ARGUMENTS**

Current state:

!`git status --short`

!`git diff --stat`

Steps:

1. **Gate first.** Confirm `/quality-gate` has passed. If it hasn't, run it now — do not
   ship unverified work.

2. **Review the final diff.** Read `git diff`. Ensure the change is minimal, on-topic, and
   free of debug code, secrets, or unrelated churn.

3. **Confirm the branch.** Verify you are on the intended working branch. Never commit to a
   different branch without explicit permission.

4. **Stage deliberately.** Add only the files that belong to this change. Do not blanket
   `git add -A` if it would sweep in unrelated files.

5. **Commit in house style.** A concise imperative subject (≤ ~70 chars) summarizing the
   *why*, then a short body if the change needs explanation. One logical change per commit.

6. **Report.** Summarize what was committed. **Do not push and do not open a PR unless the
   user explicitly asks.** If they do, push with `git push -u origin <branch>`.

Honest delivery: if anything is incomplete or skipped, say so in the summary.
