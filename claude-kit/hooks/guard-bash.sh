#!/usr/bin/env bash
# ── PreToolUse hook（匹配 Bash）──────────────────────────────────────
# 治的病：「空转卡住」+「重复犯以前的错」
#
# 两件事：
#   A. 拦截「永不返回」的命令（dev server / watch 模式）—— 这是空转的头号元凶
#   B. 执行 rules.txt 里你自己攒的禁令 —— 犯过一次的错，结构上不可能再犯
#
# 关键：CLAUDE.md 里写的规矩模型可以忽略，这里 deny 了它就是执行不了。
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

payload=$(cat)
command -v jq >/dev/null 2>&1 || exit 0

cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -n "$cmd" ] || exit 0

# 已经声明后台运行的，放行
bg=$(printf '%s' "$payload" | jq -r '.tool_input.run_in_background // false' 2>/dev/null)
[ "$bg" = "true" ] && exit 0

deny() {
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

# ── A. 阻塞型命令：前台跑就是永久卡死 ────────────────────────────────
# 注意 vitest 默认就是 watch 模式（要 `vitest run` 才跑一次），最隐蔽的坑。
# 只用 POSIX ERE，不要用负向先行断言 —— grep -E 不支持，会静默失效。
# 例外（`vitest run` / `compose up -d` 之类）一律交给下面的 case 处理。
B='(^|[[:space:];&|(])'          # 命令起始位置
E='([[:space:]]|$)'              # 词尾
blocking="${B}(npm|pnpm|yarn|bun)[[:space:]]+(run[[:space:]]+)?(dev|start|serve|watch)${E}"
blocking="$blocking|${B}(vite|nodemon|webpack-dev-server|vitest|jest|watchexec)${E}"
blocking="$blocking|${B}(next|nuxt|astro|remix)[[:space:]]+dev${E}"
blocking="$blocking|--watch${E}"
blocking="$blocking|${B}tail[[:space:]]+(-[a-zA-Z]*f|--follow)"
blocking="$blocking|${B}(watch|less|more|top|htop|journalctl[[:space:]]+-f)${E}"
blocking="$blocking|${B}(uvicorn|gunicorn|celery|ngrok)${E}"
blocking="$blocking|${B}(flask[[:space:]]+run|rails[[:space:]]+s|php[[:space:]]+-S|python[0-9]?[[:space:]]+-m[[:space:]]+http\.server)"
blocking="$blocking|docker[[:space:]]+compose[[:space:]]+up"
blocking="$blocking|docker[[:space:]]+run[[:space:]]+[^|]*-it"

if printf '%s' "$cmd" | grep -qE "$blocking"; then
  case "$cmd" in
    # 已经是「跑一次就退出」的形式，放行
    *"compose up"*"-d"*|*"vitest run"*|*"jest"*"--watchAll=false"*|*"--watch=false"*|*"--watch false"*)
      ;;
    *)
      deny "这条命令在前台不会返回，会把会话卡死：
    $cmd

改成下面之一再执行：
  · 确实需要跑起来 → 同样的命令，带 run_in_background: true，然后用 BashOutput 读日志
  · 只是想跑一次测试 → 用非 watch 形式（vitest run / jest --watchAll=false / pytest）
  · 只是想看日志 → 用 tail -n 200 而不是 tail -f"
      ;;
  esac
fi

# ── B. 你自己的禁令表 ────────────────────────────────────────────────
# 格式：每行  正则<TAB>给 Claude 看的解释
# 位置：项目 .claude/rules.txt 优先，其次 ~/.claude/rules.txt
rules_files=()
root=$(git rev-parse --show-toplevel 2>/dev/null) && rules_files+=("$root/.claude/rules.txt")
rules_files+=("$HOME/.claude/rules.txt")

for rf in "${rules_files[@]}"; do
  [ -f "$rf" ] || continue
  while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    case "$line" in \#*|" "*\#*) continue ;; esac
    # 分隔符是 => ，不是 Tab。Tab 在编辑器里会被静默转成空格，
    # 那样整张规则表会变成一个不报错的哑巴 —— 别用看不见的字符做分隔符。
    if [ "${line#*=>}" != "$line" ]; then
      pattern="${line%%=>*}"; reason="${line#*=>}"
    else
      pattern="$line"; reason=""
    fi
    pattern="${pattern%"${pattern##*[![:space:]]}"}"   # 去尾部空白
    reason="${reason#"${reason%%[![:space:]]*}"}"      # 去头部空白
    [ -z "$pattern" ] && continue
    [ -z "$reason" ] && reason="这条命令被你自己的规则挡下了：$pattern"
    # 必须用 -e：规则以 - 开头时（如 --no-verify），grep 会把它当成自己的选项，
    # 结果是规则静默失效 —— 不报错，只是永远不匹配。
    if printf '%s' "$cmd" | grep -qE -e "$pattern" 2>/dev/null; then
      deny "$reason

（这条禁令来自 $rf。如果你认为它在当前场景不该生效，停下来问用户，不要绕过。）"
    fi
  done < "$rf"
done

exit 0
