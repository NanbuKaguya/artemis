---
description: When and how to use .spec-anchor to prevent specification drift
globs: ["**/*"]
---

# Spec Anchor

Write `.spec-anchor` at the start of any task that:
- Touches more than 2 files
- Has multi-part or ambiguous requirements
- Is hard to reverse once started

**Format — write exactly this:**
```
Goal: [the problem you're solving — one sentence]
Done when: [observable, testable criteria]
Not doing: [what is explicitly out of scope]
```

**During the task:** If you're about to make a significant change, re-read the anchor. Does this serve the goal? If your changes have drifted from it, stop and decide: update the anchor (and tell the user why), or revert the drift.

**After the task:** Delete `.spec-anchor`. It's a working file, not committed state.

The anchor is not for the user. It's your own protection against context drift and scope creep in long tasks.
