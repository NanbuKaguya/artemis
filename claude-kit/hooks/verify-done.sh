#!/usr/bin/env bash
# ── Stop hook ────────────────────────────────────────────────────────
# 治的病：「说做完了，其实是坏的」/「产出质量低于预期」
#
# Claude 准备收工时，如果它这轮真的改过代码，就跑一次项目自己的检查。
# 没过就把它打回去继续修 —— 你不需要先发现问题再骂它一遍。
#
# 三重保险，避免它变成新的折磨：
#   1. 没改代码 → 直接放行，零开销
#   2. 同一会话最多打回 2 次 → 绝不死循环
#   3. 检查命令来自项目自己的配置 → 不猜、不自作主张
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

payload=$(cat)
command -v jq >/dev/null 2>&1 || exit 0

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0

# ── 1. 这轮改代码了吗？没有就别浪费时间 ──────────────────────────────
changed=$(git status --porcelain 2>/dev/null \
  | grep -cE '\.(ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|rb|php)$' 2>/dev/null || echo 0)
[ "${changed:-0}" -gt 0 ] || exit 0

# ── 2. 熔断：每个会话最多打回 2 次 ───────────────────────────────────
sid=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"' 2>/dev/null)
counter="${TMPDIR:-/tmp}/claude-verify-done.${sid}"
n=$(cat "$counter" 2>/dev/null || echo 0)
[ "${n:-0}" -ge 2 ] && exit 0

# ── 3. 跑项目自己声明的检查 ──────────────────────────────────────────
# 优先级：.claude/verify.sh（你自己写的）> package.json scripts > 语言默认
check_cmd=""
if [ -x .claude/verify.sh ]; then
  check_cmd=".claude/verify.sh"
elif [ -f package.json ]; then
  pm=npm
  [ -f pnpm-lock.yaml ] && pm=pnpm
  [ -f yarn.lock ] && pm=yarn
  [ -f bun.lockb ] && pm=bun
  for s in typecheck check lint; do
    if jq -e --arg s "$s" '.scripts[$s]' package.json >/dev/null 2>&1; then
      check_cmd="$pm run $s"; break
    fi
  done
elif [ -f pyproject.toml ] && command -v ruff >/dev/null 2>&1; then
  check_cmd="ruff check ."
elif [ -f go.mod ]; then
  check_cmd="go build ./..."
elif [ -f Cargo.toml ]; then
  check_cmd="cargo check --quiet"
fi

[ -n "$check_cmd" ] || exit 0

out=$(timeout 180 bash -c "$check_cmd" 2>&1)
status=$?
[ $status -eq 0 ] && { rm -f "$counter"; exit 0; }

echo $((n + 1)) > "$counter"
out=$(printf '%s' "$out" | tail -60)

jq -n --arg c "$check_cmd" --arg o "$out" '{
  decision: "block",
  reason: ("收工前的自动检查没过，回去修完再停。\n\n$ \($c)\n\($o)\n\n如果这些失败在你改动之前就存在、和你无关，明确说出来，不要默默忽略。")
}'
exit 0
