#!/usr/bin/env bash
# AAWS PreToolUse guard — blocks obviously destructive Bash commands.
# Wired in via .claude/settings.json (see docs/settings.example.json).
# Reads the tool-call JSON on stdin; exit 2 blocks the command and shows stderr.
set -euo pipefail

input="$(cat)"

# Extract the command string from the tool input (jq preferred, grep fallback).
if command -v jq >/dev/null 2>&1; then
  cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"
else
  cmd="$(printf '%s' "$input" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//')"
fi

[ -z "${cmd:-}" ] && exit 0

# Patterns we refuse to run unattended.
deny_patterns=(
  'rm[[:space:]]+-rf[[:space:]]+/'      # rm -rf / ...
  'rm[[:space:]]+-rf[[:space:]]+~'      # rm -rf ~ ...
  ':\(\)\{.*\};:'                       # fork bomb
  'mkfs'                                # format filesystem
  'dd[[:space:]]+if=.*of=/dev/'         # raw disk overwrite
  'git[[:space:]]+push.*--force'        # force push
  '>[[:space:]]*/dev/sd'                # write to raw disk
  'chmod[[:space:]]+-R[[:space:]]+777[[:space:]]+/'
)

for pat in "${deny_patterns[@]}"; do
  if printf '%s' "$cmd" | grep -Eq "$pat"; then
    echo "AAWS guard: refused destructive command matching /$pat/. Run it manually if truly intended." >&2
    exit 2
  fi
done

exit 0
