#!/usr/bin/env bash
# 装到 ~/.claude/，对你所有项目生效。
#
#   ./install.sh          安装 / 更新
#   ./install.sh --dry    只看会改什么，不动手
#
# 反复运行是安全的：settings.json 是合并不是覆盖，你已有的配置会保留；
# 本套件自己的 hook 条目会被替换而不是重复堆积。
# 你已经存在的 CLAUDE.md / rules.txt 绝不会被覆盖。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.claude"
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

say()  { printf '  %s\n' "$*"; }
step() { printf '\n▸ %s\n' "$*"; }

command -v jq >/dev/null 2>&1 || {
  echo "需要 jq。装一下：brew install jq / apt install jq" >&2; exit 1; }

step "目标目录 $DEST"
[ $DRY -eq 1 ] || mkdir -p "$DEST/hooks"

# ── 1. hooks ─────────────────────────────────────────────────────────
step "安装 hooks"
for h in "$SRC"/hooks/*.sh; do
  name=$(basename "$h")
  say "$name"
  [ $DRY -eq 1 ] && continue
  install -m 755 "$h" "$DEST/hooks/$name"
done

# ── 2. settings.json（合并，不覆盖）──────────────────────────────────
step "合并 settings.json"
if [ ! -f "$DEST/settings.json" ]; then
  say "原本没有，直接写入"
  [ $DRY -eq 1 ] || cp "$SRC/settings.json" "$DEST/settings.json"
else
  backup="$DEST/settings.json.bak.$(date +%Y%m%d%H%M%S)"
  say "已存在 → 备份到 $(basename "$backup")，然后合并"
  merged=$(jq -s '
    .[0] as $old | .[1] as $new |
    ($old * $new)
    | .permissions.allow =
        ((($old.permissions.allow // []) + ($new.permissions.allow // [])) | unique)
    | .permissions.deny =
        ((($old.permissions.deny  // []) + ($new.permissions.deny  // [])) | unique)
    | .hooks = (
        reduce (($new.hooks // {}) | keys[]) as $k (($old.hooks // {});
          .[$k] = (
            # 丢掉本套件上次装的条目，避免重装后重复执行
            (((.[$k]) // [])
              | map(select(
                  ((.hooks // []) | map(.command? // "") | join(" "))
                  | test("\\.claude/hooks/(verify-edit|verify-done|guard-bash|session-brief)\\.sh") | not
                )))
            + ($new.hooks[$k])
          )
        )
      )
  ' "$DEST/settings.json" "$SRC/settings.json")
  printf '%s' "$merged" | jq empty || { echo "合并结果不是合法 JSON，已中止，原文件未动" >&2; exit 1; }
  if [ $DRY -eq 0 ]; then
    cp "$DEST/settings.json" "$backup"
    printf '%s\n' "$merged" > "$DEST/settings.json"
  else
    say "（dry run）合并后的 permissions.allow 共 $(printf '%s' "$merged" | jq '.permissions.allow|length') 条"
  fi
fi

# ── 3. 两个「你的」文件：只在不存在时放，永不覆盖 ────────────────────
step "个人文件（已存在则跳过，不覆盖）"
for f in CLAUDE.md rules.txt; do
  if [ -e "$DEST/$f" ]; then
    say "$f 已存在 → 跳过（想看新版本：$SRC/$f）"
  else
    say "$f → 写入"
    [ $DRY -eq 1 ] || cp "$SRC/$f" "$DEST/$f"
  fi
done

# ── 4. 自检 ──────────────────────────────────────────────────────────
step "自检"
if [ $DRY -eq 0 ]; then
  jq -e '.hooks.PostToolUse' "$DEST/settings.json" >/dev/null \
    && say "✓ settings.json 合法，hooks 已就位" \
    || { echo "✗ settings.json 有问题，检查 $DEST/settings.json" >&2; exit 1; }
  for h in verify-edit guard-bash session-brief verify-done; do
    [ -x "$DEST/hooks/$h.sh" ] || { echo "✗ $h.sh 没装上" >&2; exit 1; }
  done
  say "✓ 4 个 hook 均可执行"
fi

cat <<'EOF'

装好了。还差最后一步：

  在 Claude Code 里执行一次  /hooks  （或重启 claude）
  ——— 配置监听器只在会话启动时读取，不走这一步新 hook 不会生效。

然后做这两件事，收益最大：

  1. 打开 ~/.claude/rules.txt，把示例改成你自己的。
     以后它每犯一次同样的错，你就往里加一行 —— 这是「不再重复犯错」的
     唯一可靠办法，口头纠正只活到本次会话结束。

  2. 在每个常用项目根目录写一份 CLAUDE.md，只写四件事：
     这个项目是干什么的 / 目录怎么分 / 怎么跑测试 / 有哪些坑。
     控制在 40 行内。

EOF
