#!/usr/bin/env bash
# AAWS SessionStart hook — prints a short orientation banner.
# Wired in via .claude/settings.json (see docs/settings.example.json).
set -euo pipefail

cat <<'BANNER'
┌─ Artemis Agent Work System ────────────────────────────────┐
│ Orchestrate → Delegate → Verify.                           │
│ Specialists: .claude/agents/   Playbooks: .claude/skills/  │
│ /plan-work  /quality-gate  /forge-agent  /forge-skill  /ship │
└────────────────────────────────────────────────────────────┘
BANNER

exit 0
