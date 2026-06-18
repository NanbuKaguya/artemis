---
paths:
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/test_*.py"
  - "**/tests/**"
  - "**/__tests__/**"
---

# Testing Rules (applies when editing tests)

- **Use the project's existing framework and helpers.** Tests should read like the
  existing suite.
- **Test behavior, not implementation.** Assert observable outcomes; avoid coupling to
  internal details that make tests brittle.
- **Cover the risky paths.** Happy path, boundaries, and error handling — not just the
  easy case. Coverage is a means, not the goal.
- **One reason to fail.** Each test has a clear name and fails for one understandable
  reason.
- **Run them.** Execute the suite and report actual results, including failures with output.
  Never mark green without running.
