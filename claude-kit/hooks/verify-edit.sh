#!/usr/bin/env bash
# ── PostToolUse hook（匹配 Edit|Write）────────────────────────────────
# 治的病：「跑着跑着就出问题」
#
# Claude 每改完一个文件，立刻对这个文件做快速检查。有问题就把错误原文
# 塞回它的上下文，它会当场修 —— 而不是攒到最后由你发现。
#
# 设计约束：必须快（全部检查加起来 < 3 秒），慢检查会把「空转」问题变严重。
# 所以这里只做单文件级别的快检查，全项目类型检查交给 verify-done.sh。
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

payload=$(cat)
command -v jq >/dev/null 2>&1 || exit 0

file=$(printf '%s' "$payload" | jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)
[ -n "$file" ] && [ -f "$file" ] || exit 0

case "$file" in
  */node_modules/*|*/.git/*|*/dist/*|*/build/*|*/vendor/*|*/.venv/*) exit 0 ;;
esac

cd "$(dirname "$file")" 2>/dev/null || exit 0
root=$(git rev-parse --show-toplevel 2>/dev/null) || root=$(pwd)

problems=""
note() { problems="${problems}${1}"$'\n'; }
have() { command -v "$1" >/dev/null 2>&1; }
# 本地依赖优先：项目里装的工具版本才是对的
local_bin() { [ -x "$root/node_modules/.bin/$1" ] && echo "$root/node_modules/.bin/$1"; }

# ── 1. 冲突标记：任何语言，一票否决 ──────────────────────────────────
if grep -nE '^(<{7}|={7}|>{7})( |$)' "$file" >/dev/null 2>&1; then
  note "遗留了 git 冲突标记（<<<<<<< / ======= / >>>>>>>），文件是坏的，必须清理。"
fi

ext="${file##*.}"

# ── 2. 按语言做快检查 ────────────────────────────────────────────────
case "$ext" in
  ts|tsx|js|jsx|mjs|cjs)
    if bin=$(local_bin biome); then
      out=$(timeout 20 "$bin" check "$file" 2>&1) || note "biome:"$'\n'"$out"
    elif bin=$(local_bin eslint); then
      out=$(timeout 25 "$bin" --format unix "$file" 2>&1) || note "eslint:"$'\n'"$out"
    elif have node && [ "$ext" != "ts" ] && [ "$ext" != "tsx" ]; then
      out=$(timeout 10 node --check "$file" 2>&1) || note "语法错误:"$'\n'"$out"
    fi
    ;;
  py)
    if have ruff; then
      out=$(timeout 20 ruff check "$file" 2>&1) || note "ruff:"$'\n'"$out"
    elif have python3; then
      out=$(timeout 10 python3 -m py_compile "$file" 2>&1) || note "语法错误:"$'\n'"$out"
    fi
    ;;
  go)
    have gofmt && { out=$(timeout 10 gofmt -l "$file" 2>&1); [ -n "$out" ]; } \
      && note "gofmt 未格式化：$out（跑 gofmt -w）"
    have go && { out=$(timeout 30 go vet "./$(basename "$(pwd)")" 2>&1) || note "go vet:"$'\n'"$out"; }
    ;;
  rs)
    have rustfmt && { out=$(timeout 15 rustfmt --check "$file" 2>&1); [ -n "$out" ]; } \
      && note "rustfmt 未格式化（跑 cargo fmt）"
    ;;
  json)
    out=$(timeout 5 jq empty "$file" 2>&1) || note "JSON 非法:"$'\n'"$out"
    ;;
  yml|yaml)
    have python3 && { out=$(timeout 10 python3 -c \
      'import sys,yaml;yaml.safe_load(open(sys.argv[1]))' "$file" 2>&1) || note "YAML 非法:"$'\n'"$out"; }
    ;;
esac

# ── 3. 调试残留：不阻断，但提醒它自己清 ──────────────────────────────
case "$ext" in
  ts|tsx|js|jsx|py)
    junk=$(grep -nE '(^|[^.\w])(debugger;|console\.log\(|pdb\.set_trace\(|breakpoint\(\))' "$file" 2>/dev/null | head -5)
    [ -n "$junk" ] && note "疑似调试残留（确认是否该删）:"$'\n'"$junk"
    ;;
esac

[ -z "$problems" ] && exit 0

# 用 additionalContext 把问题喂回模型 —— 它会在下一步自己修
jq -n --arg f "$file" --arg p "$problems" '{
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    additionalContext: ("【自动检查】刚写的 \($f) 有问题，现在就修掉，不要继续下一步：\n\($p)")
  }
}'
exit 0
