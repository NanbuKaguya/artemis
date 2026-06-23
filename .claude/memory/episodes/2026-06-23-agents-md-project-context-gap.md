## What happened
While rebuilding Artemis v3 from a 16-agent complex system to a lean 3-agent context engineering system, the behavioral layer (CLAUDE.md) was kept under 500 tokens and every agent, skill, rule, and hook was evidence-justified. Analysis of Harness Engineering patterns then surfaced a structural gap: CLAUDE.md was serving two purposes simultaneously — behavioral instructions (the operating loop) and project context (what Artemis is, where things live, change constraints). These two concerns compete for the same token budget, and when project context grows, it dilutes behavioral instructions.

## Root cause
Single-layer context architecture forces behavioral instructions and project facts into the same file, creating bloat pressure that degrades instruction-following — exactly the failure mode Artemis was designed to prevent.

## What changes next time
When reviewing or setting up any Claude Code project, explicitly check whether CLAUDE.md carries project context that could be separated into a root-level AGENTS.md. The split is: CLAUDE.md = how Claude works (loop, constraints, delegation rules); AGENTS.md = what this project is (structure, constraints on changes, current state).

## Signal
MEDIUM — this changes the evaluation checklist for any Claude Code configuration review, but does not change the core loop or verification approach.
