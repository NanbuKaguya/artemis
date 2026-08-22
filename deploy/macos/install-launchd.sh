#!/usr/bin/env bash
# macOS 定时任务安装（launchd）
#
# 只在你已经手动跑满一个月、确认输出有用之后再做这一步。
# 不需要 sudo —— 装的是用户级 LaunchAgent，登录后生效。
#
# 用法：  bash deploy/macos/install-launchd.sh

set -uo pipefail
GRN=$'\033[32m'; YLW=$'\033[33m'; RED=$'\033[31m'; BOLD=$'\033[1m'; RST=$'\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VPY="$ROOT/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
LOGDIR="$ROOT/logs"

[ -x "$VPY" ] || { printf "${RED}✗ 找不到 %s${RST}\n  先跑 bash bootstrap.sh\n" "$VPY"; exit 1; }
mkdir -p "$AGENTS" "$LOGDIR"

# ---------------------------------------------------------------- 时区检查
# launchd 的 StartCalendarInterval 用的是**本机时区**，不是北京时间。
# Mac 不在中国时区时，08:40 会落在完全错误的时刻，而且不会有任何报错。
TZNAME="$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')"
OFFSET="$(date +%z)"
printf "${BOLD}时区检查${RST}\n"
printf "  本机时区: %s (UTC%s)\n" "${TZNAME:-未知}" "$OFFSET"
if [ "$OFFSET" = "+0800" ]; then
  printf "  ${GRN}✓${RST} 与北京时间一致，定时时刻可直接使用\n\n"
  TZ_OK=1
else
  printf "  ${YLW}▲ 本机不是 UTC+8。launchd 按本机时区触发，${RST}\n"
  printf "  ${YLW}  下面的 08:40/15:30 会落在错误的时刻，且不会报错。${RST}\n"
  printf "  ${YLW}  出国/改时区后请重跑本脚本。${RST}\n\n"
  TZ_OK=0
fi

make_plist() {
  local label="$1" hour="$2" minute="$3" shift_n="$4"
  shift 4
  local plist="$AGENTS/$label.plist"
  {
    printf '<?xml version="1.0" encoding="UTF-8"?>\n'
    printf '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    printf '<plist version="1.0">\n<dict>\n'
    printf '  <key>Label</key><string>%s</string>\n' "$label"
    printf '  <key>ProgramArguments</key>\n  <array>\n'
    for a in "$@"; do printf '    <string>%s</string>\n' "$a"; done
    printf '  </array>\n'
    printf '  <key>WorkingDirectory</key><string>%s</string>\n' "$ROOT"
    printf '  <key>EnvironmentVariables</key>\n  <dict>\n'
    printf '    <key>TZ</key><string>Asia/Shanghai</string>\n'
    printf '    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin</string>\n'
    printf '  </dict>\n'
    printf '  <key>StartCalendarInterval</key>\n  <array>\n'
    for wd in 1 2 3 4 5; do
      if [ "$shift_n" = "monthly" ]; then break; fi
      printf '    <dict><key>Weekday</key><integer>%s</integer>' "$wd"
      printf '<key>Hour</key><integer>%s</integer>' "$hour"
      printf '<key>Minute</key><integer>%s</integer></dict>\n' "$minute"
    done
    if [ "$shift_n" = "monthly" ]; then
      printf '    <dict><key>Day</key><integer>1</integer>'
      printf '<key>Hour</key><integer>%s</integer>' "$hour"
      printf '<key>Minute</key><integer>%s</integer></dict>\n' "$minute"
    fi
    printf '  </array>\n'
    printf '  <key>StandardOutPath</key><string>%s/%s.log</string>\n' "$LOGDIR" "$label"
    printf '  <key>StandardErrorPath</key><string>%s/%s.err</string>\n' "$LOGDIR" "$label"
    printf '  <key>RunAtLoad</key><false/>\n'
    printf '</dict>\n</plist>\n'
  } > "$plist"

  # 校验 XML 合法性，坏 plist 会被 launchd 静默忽略
  if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$plist" >/dev/null 2>&1 || { printf "${RED}✗ %s 格式非法${RST}\n" "$plist"; return 1; }
  fi

  launchctl unload "$plist" 2>/dev/null || true
  launchctl load  "$plist" 2>/dev/null && printf "  ${GRN}✓${RST} %s\n" "$label" \
    || printf "  ${RED}✗ %s 加载失败${RST}\n" "$label"
}

printf "${BOLD}安装定时任务${RST}\n"
make_plist com.artemis.premarket  8 40 weekly  "$VPY" -m artemis.brief premarket
make_plist com.artemis.postmarket 15 30 weekly "$VPY" -m artemis.brief postmarket
make_plist com.artemis.calendar    3  0 monthly "$VPY" -m artemis.service calendar-refresh

cat <<TIP

${BOLD}────────────────────────────────────────────────${RST}
装好了。说明：

  盘前简报  工作日 08:40   （早于 09:15 集合竞价）
  盘后复盘  工作日 15:30
  日历刷新  每月 1 号 03:00

  日志:     $LOGDIR/
  查看已装: launchctl list | grep artemis
  手动触发: launchctl start com.artemis.premarket
  卸载:     launchctl unload ~/Library/LaunchAgents/com.artemis.*.plist

${YLW}两个 macOS 特有的注意点：${RST}

  1. ${BOLD}合盖睡眠时不会触发。${RST}launchd 会在唤醒后补跑一次错过的任务，
     所以你可能在 10 点打开电脑才看到"盘前"简报 —— 那时已经开盘了。
     真要准时，去 系统设置 > 节能 里设定时唤醒。

  2. ${BOLD}定时用的是本机时区。${RST}$([ "$TZ_OK" = 1 ] && echo "当前是 UTC+8，没问题。" || echo "当前不是 UTC+8，时刻是错的！")
     改时区或出国后要重跑本脚本。
${BOLD}────────────────────────────────────────────────${RST}
TIP
