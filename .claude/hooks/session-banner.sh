#!/usr/bin/env bash
# SessionStart hook — orientation banner + spec anchor reminder.
set -euo pipefail

cat <<'BANNER'
┌─ Artemis ──────────────────────────────────────────────────────┐
│ Loop: CLARIFY → ANCHOR → BUILD → VERIFY → LEARN               │
│ Agents: inspector · researcher · reviewer                      │
│ Skills: /quality-gate · /reflect                               │
│ Rules:  spec-anchor · handoff-contracts · episode-format       │
└────────────────────────────────────────────────────────────────┘
BANNER

# Remind about pending spec anchor from prior session
if [ -f ".spec-anchor" ]; then
  echo ""
  echo "📌 .spec-anchor found from a previous session:"
  cat .spec-anchor
  echo ""
fi

# Show learned rules count
learned=".claude/rules/learned.md"
if [ -f "$learned" ]; then
  rule_count=$(grep -c "^## " "$learned" 2>/dev/null || echo "0")
  if [ "$rule_count" -gt 0 ]; then
    echo "📚 $rule_count learned rule(s) active — see .claude/rules/learned.md"
  fi
fi

# Show episode count
episode_count=$(find .claude/memory/episodes -name "*.md" ! -name ".gitkeep" 2>/dev/null | wc -l | tr -d ' ')
if [ "$episode_count" -gt 0 ]; then
  echo "🗂  $episode_count episode(s) in memory"
  if [ "$episode_count" -ge 5 ]; then
    echo "   → Consider running /reflect to distill rules"
  fi
fi

exit 0
