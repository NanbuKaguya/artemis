#!/usr/bin/env bash
# PreToolUse guard — blocks destructive Bash commands.
# Wired in via .claude/settings.json (see docs/settings.example.json).
# Reads the tool-call JSON on stdin; exit 2 blocks the command and shows stderr.
set -euo pipefail

input="$(cat)"

if command -v jq >/dev/null 2>&1; then
  cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"
else
  cmd="$(printf '%s' "$input" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//')"
fi

[ -z "${cmd:-}" ] && exit 0

deny_patterns=(
  'rm[[:space:]]+-rf[[:space:]]+/'
  'rm[[:space:]]+-rf[[:space:]]+~'
  ':\(\)\{.*\};:'
  'mkfs'
  'dd[[:space:]]+if=.*of=/dev/'
  'git[[:space:]]+push.*--force'
  '>[[:space:]]*/dev/sd'
  'chmod[[:space:]]+-R[[:space:]]+777[[:space:]]+'
)

for pat in "${deny_patterns[@]}"; do
  if printf '%s' "$cmd" | grep -Eq "$pat"; then
    echo "Guard: refused destructive command matching /$pat/. Run it manually if truly intended." >&2
    exit 2
  fi
done

exit 0
