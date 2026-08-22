#!/usr/bin/env bash
# Artemis 部署脚本。幂等，可重复跑。
set -euo pipefail

ARTEMIS_HOME="${ARTEMIS_HOME:-/opt/artemis}"
STATE_DIR="${STATE_DIR:-/var/lib/artemis}"
REPO="${REPO:-https://github.com/NanbuKaguya/artemis.git}"
BRANCH="${BRANCH:-claude/blissful-mccarthy-xprsgj}"

echo "==> 1/6 创建用户与目录"
id -u artemis &>/dev/null || useradd --system --home "$STATE_DIR" --shell /usr/sbin/nologin artemis
mkdir -p "$ARTEMIS_HOME" "$STATE_DIR"/{data_cache,briefs} /etc/artemis
chown -R artemis:artemis "$STATE_DIR"

echo "==> 2/6 拉取代码"
if [ -d "$ARTEMIS_HOME/.git" ]; then
  git -C "$ARTEMIS_HOME" fetch origin "$BRANCH" && git -C "$ARTEMIS_HOME" checkout "$BRANCH" && git -C "$ARTEMIS_HOME" pull origin "$BRANCH"
else
  git clone -b "$BRANCH" "$REPO" "$ARTEMIS_HOME"
fi

echo "==> 3/6 建虚拟环境"
python3 -m venv "$ARTEMIS_HOME/.venv"
"$ARTEMIS_HOME/.venv/bin/pip" install --quiet --upgrade pip
"$ARTEMIS_HOME/.venv/bin/pip" install --quiet -e "$ARTEMIS_HOME[data]"

echo "==> 4/6 配置文件"
[ -f /etc/artemis/artemis.env ] || {
  cp "$ARTEMIS_HOME/deploy/artemis.env.example" /etc/artemis/artemis.env
  echo "    已生成 /etc/artemis/artemis.env —— 请编辑后再启用定时器"
}
chmod 640 /etc/artemis/artemis.env
chown root:artemis /etc/artemis/artemis.env
[ -f "$STATE_DIR/watchlist.txt" ] || {
  printf '# 每行一个 6 位代码，# 开头为注释\n' > "$STATE_DIR/watchlist.txt"
  chown artemis:artemis "$STATE_DIR/watchlist.txt"
}

echo "==> 5/6 安装 systemd 单元"
cp "$ARTEMIS_HOME"/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload

echo "==> 6/6 自检"
sudo -u artemis env "ARTEMIS_DATA_DIR=$STATE_DIR/data_cache" \
  "$ARTEMIS_HOME/.venv/bin/python" -m artemis.service health || true

cat <<'TIP'

下一步（按顺序）：
  1. 编辑 /etc/artemis/artemis.env，确认 ARTEMIS_LLM_BASE_URL 指向你的 Hermes
  2. 把自选股写进 /var/lib/artemis/watchlist.txt
  3. 刷新交易日历（必做，否则节假日会被当成交易日）：
       systemctl start artemis-calendar.service
  4. 手动跑一次看输出：
       sudo -u artemis /opt/artemis/.venv/bin/python -m artemis.brief premarket
  5. 确认无误后启用定时器：
       systemctl enable --now artemis-calendar.timer
       systemctl enable --now artemis-brief@premarket.timer
       systemctl enable --now artemis-brief@postmarket.timer
  6. 查看下次触发时间：
       systemctl list-timers 'artemis*'
TIP
