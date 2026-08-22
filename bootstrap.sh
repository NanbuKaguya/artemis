#!/usr/bin/env bash
# Artemis 一键落地（macOS / Linux / WSL）
#
# 设计原则：
#   · 不需要 sudo，全部装在当前目录
#   · 幂等，可重复跑
#   · 停在第一个真问题上，并给出可操作的下一步
#   · 每一步都验证结果，而不是假设它成功了
#
# 用法：  bash bootstrap.sh

set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'
YLW=$'\033[33m'; RST=$'\033[0m'

say()  { printf "%s\n" "$*"; }
step() { printf "\n${BOLD}==> %s${RST}\n" "$*"; }
ok()   { printf "  ${GRN}✓${RST} %s\n" "$*"; }
warn() { printf "  ${YLW}▲${RST} %s\n" "$*"; }
die()  { printf "\n  ${RED}✗ %s${RST}\n\n" "$*"; [ $# -gt 1 ] && printf "  %s\n\n" "$2"; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
cd "$ROOT"

say "${BOLD}Artemis 一键落地${RST}"
say "${DIM}目录: $ROOT${RST}"

# ---------------------------------------------------------------- 1. Python
step "1/6 检查 Python"
PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  command -v "$c" >/dev/null 2>&1 || continue
  if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || die "找不到 Python 3.11+" \
  "macOS:  brew install python@3.12
  Ubuntu: sudo apt install python3.12 python3.12-venv
  其他:   https://www.python.org/downloads/"
ok "$($PY --version) ($(command -v "$PY"))"

# ---------------------------------------------------------------- 2. venv
step "2/6 创建虚拟环境"
if [ -d "$VENV" ]; then
  ok "已存在，复用 .venv"
else
  "$PY" -m venv "$VENV" 2>/dev/null || die "创建虚拟环境失败" \
    "Ubuntu/Debian 需要单独装 venv：sudo apt install python3-venv"
  ok "已创建 .venv"
fi
VPY="$VENV/bin/python"
[ -x "$VPY" ] || die "虚拟环境不完整：$VPY 不存在"

# ---------------------------------------------------------------- 3. 依赖
step "3/6 安装依赖（首次约 2-4 分钟）"
"$VPY" -m pip install --quiet --upgrade pip 2>/dev/null
if "$VPY" -m pip install --quiet -e "$ROOT[data]" 2>/tmp/artemis_pip.log; then
  ok "核心依赖 + AkShare 安装完成"
else
  warn "带 AkShare 的安装失败，退回只装核心依赖"
  say "${DIM}     $(tail -3 /tmp/artemis_pip.log | head -1)${RST}"
  "$VPY" -m pip install --quiet -e "$ROOT" 2>/dev/null \
    || die "核心依赖也装不上" "看完整日志：cat /tmp/artemis_pip.log
  国内网络慢可以换源：
    $VPY -m pip install -e '$ROOT[data]' -i https://pypi.tuna.tsinghua.edu.cn/simple"
  ok "核心依赖已装（AkShare 缺失，排雷功能不可用）"
fi

# 验证真的能导入，而不是相信 pip 的退出码
"$VPY" -c "import artemis.lite, artemis.service, artemis.doctor" 2>/dev/null \
  || die "包装上了但导入失败" "请把这条命令的输出发给我：
    $VPY -c 'import artemis.lite'"
ok "模块导入验证通过"

# ---------------------------------------------------------------- 4. 自检
step "4/6 环境体检"
"$VPY" -m artemis.doctor
DOCTOR_RC=$?

# ---------------------------------------------------------------- 5. 交易日历
step "5/6 交易日历"
if [ $DOCTOR_RC -eq 0 ]; then
  if "$VPY" -m artemis.service calendar-refresh 2>/dev/null | grep -q '"ok": true'; then
    ok "已刷新（没有它，节假日会被当成交易日）"
  else
    warn "刷新失败 —— 多半是连不上数据源，见上面体检结果"
  fi
else
  warn "体检有阻塞项，跳过日历刷新。修完后手动跑："
  say "  ${DIM}$VPY -m artemis.service calendar-refresh${RST}"
fi

# ---------------------------------------------------------------- 6. 自选股
step "6/6 自选股清单"
# 用 POSIX 字符类而不是 \s —— macOS 自带的是 BSD grep，不认 GNU 的 \s，
# 会把缩进的注释行误计成股票代码
if [ -s "$ROOT/watchlist.txt" ] && grep -qv '^[[:space:]]*#' "$ROOT/watchlist.txt" 2>/dev/null; then
  N=$(grep -cve '^[[:space:]]*#' -e '^[[:space:]]*$' "$ROOT/watchlist.txt" 2>/dev/null || echo 0)
  ok "已有 $N 只"
else
  cat > "$ROOT/watchlist.txt" <<'WL'
# 每行一个 6 位股票代码，# 开头为注释
# 删掉下面的示例，换成你自己的持仓和候选
600519
000001
WL
  ok "已创建模板 watchlist.txt（含 2 只示例，请替换）"
fi

# ---------------------------------------------------------------- 收尾
ACT="$VENV/bin/activate"
say ""
say "${BOLD}────────────────────────────────────────────────────${RST}"
if [ $DOCTOR_RC -eq 0 ]; then
  say "${GRN}${BOLD}安装完成。${RST}"
  say ""
  say "接下来（每次开新终端都要先激活环境）："
  say ""
  say "  ${BOLD}source $ACT${RST}"
  say ""
  say "  1. 编辑 watchlist.txt，填上你的自选股"
  say "  2. ${BOLD}artemis watch${RST}      ← 每天开盘前跑，标 ❌ 的今天不碰"
  say "  3. ${BOLD}artemis log${RST}        ← 每次下单前跑，写下理由和失效条件"
  say "  4. ${BOLD}artemis review${RST}     ← 每周跑，看临时起意占比"
  say ""
  say "${DIM}就这四步。不需要 Hermes、systemd、Level-2、财务数据。${RST}"
  say "${DIM}跑满一个月再考虑 docs/07 和 docs/08 里的可选项。${RST}"
else
  say "${YLW}${BOLD}安装完成，但体检有阻塞项。${RST}"
  say ""
  say "按上面「下一步」的提示修复，然后重跑："
  say ""
  say "  ${BOLD}bash bootstrap.sh${RST}"
  say ""
  say "${DIM}脚本是幂等的，重复跑不会有副作用。${RST}"
fi
say "${BOLD}────────────────────────────────────────────────────${RST}"
