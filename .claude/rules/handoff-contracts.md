---
description: Format for delegating to subagents and reading their results
---

# Handoff Contracts

Every subagent delegation needs a clear contract — free-form delegation is the primary source of multi-agent failure.

## Delegation format (you → subagent)

```markdown
## Task
[One sentence: what to accomplish]

## Input
[The specific artifact, files, or data this agent needs — nothing else]

## Output Format
[Exact structure expected back — JSON schema, list format, specific fields]

## Acceptance Criteria
[How you'll judge if the output is good enough to use]
```

## Inspector specifically

The inspector receives **only**:
```markdown
## Artifact
[The output to inspect — code diff, document, plan — verbatim]

## Inspection Mandate
[What to find: e.g., "correctness bugs and security vulnerabilities"]
```

Never give the inspector: the context that produced the artifact, why it was built this way, or what you were trying to achieve. That information biases the review toward agreement. The cold read is the mechanism.

## Agent response format

Agents return structured output per their declared output contract. If an agent returns free-form text when you asked for JSON, ask it to reformat before using the output.
