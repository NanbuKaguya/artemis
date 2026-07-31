#!/usr/bin/env bash
# ── SessionStart hook ────────────────────────────────────────────────
# 治的病：「空转」（一上来先花五分钟摸索项目）
#
# 开局就把它本来要靠翻文件才能知道的事直接告诉它：现在在哪个分支、
# 有什么没提交、依赖装没装、这个项目怎么跑测试。
#
# 刻意保持简短 —— 这段会占掉每个会话的上下文，超过 20 行就是负资产。
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail
command -v jq >/dev/null 2>&1 || exit 0

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0

info=""
add() { info="${info}${1}"$'\n'; }

# 用 --show-current：在还没有任何提交的仓库里，rev-parse 会同时输出 "HEAD"
# 并返回非零，导致 fallback 也执行，拼出 "HEAD\n?" 这种脏值。
branch=$(git branch --show-current 2>/dev/null)
[ -n "$branch" ] || branch='(未在分支上)'
dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
add "分支 ${branch} · 未提交改动 ${dirty} 处"

[ "${dirty:-0}" -gt 0 ] && add "$(git status --porcelain 2>/dev/null | head -8)"

# 依赖装了没 —— 没装就直接跑命令，是「跑着就出问题」的经典来源
if [ -f package.json ] && [ ! -d node_modules ]; then
  add "⚠ node_modules 不存在，跑任何 npm/pnpm 脚本前先装依赖"
fi
if [ -f requirements.txt ] || [ -f pyproject.toml ]; then
  [ -n "${VIRTUAL_ENV:-}" ] || add "⚠ 没有激活的 virtualenv，注意别装到系统 python"
fi

# 这个项目怎么验证 —— 省掉它自己去猜
if [ -f package.json ] && command -v jq >/dev/null 2>&1; then
  scripts=$(jq -r '.scripts | keys | join(", ")' package.json 2>/dev/null)
  [ -n "$scripts" ] && [ "$scripts" != "null" ] && add "可用脚本: ${scripts}"
fi

jq -n --arg i "$info" '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: ("【项目现状】\n\($i)")
  }
}'
exit 0
