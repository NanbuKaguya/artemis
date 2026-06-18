---
paths:
  - "src/**"
  - "lib/**"
  - "app/**"
  - "packages/**"
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.go"
  - "**/*.rs"
  - "**/*.java"
---

# Engineering Baseline (applies when editing source code)

- **Read before you write.** Understand the surrounding code and match its style, naming,
  and idioms. New code should be indistinguishable from what's already there.
- **Smallest correct change.** Keep diffs minimal and on-topic. Don't refactor unrelated
  code; flag larger refactors instead of folding them in silently.
- **Handle errors and edges.** Validate inputs at boundaries; don't swallow errors.
- **No secrets in code.** Never hardcode credentials, tokens, or keys.
- **Prove it.** Run the build and tests for what you touched; report real results.
- **No new dependency** when the stdlib or an existing one suffices; justify any addition.
